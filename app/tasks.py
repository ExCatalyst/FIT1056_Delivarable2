"""Volunteer task management (F-05)."""
from typing import List

from .errors import ConflictError, NotFound, PermissionDenied, ValidationError
from .models import InventoryItem, IssueReport, IssueType, Order, Role, Task, TaskStatus, User
from .security import check_site, require, resolve_site

ALLOWED_TRANSITIONS = {
    TaskStatus.NOT_STARTED: {TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED},
    TaskStatus.IN_PROGRESS: {TaskStatus.COMPLETED},
    TaskStatus.COMPLETED: set(),
}


class TaskService:
    def __init__(self, ctx):
        self.ctx = ctx

    def assignable_volunteers(self, actor: User) -> List[dict]:
        """Give staff a safe assignment picker without exposing account credentials."""
        actor = self.ctx.refresh(actor)
        require(actor, "task.manage")
        users = self.ctx.store.find("users", User,
                                    lambda u: u.role == Role.VOLUNTEER and u.active
                                    and not u.locked and u.site_id == actor.site_id)
        return [{"id": u.id, "name": u.full_name or u.username} for u in sorted(users, key=lambda u: u.id)]

    def create_task(self, actor: User, title: str, assigned_to: str, description: str = "", order_id: str = None) -> Task:
        """FR-VTM-01: staff create and assign a task to a volunteer in their own site."""
        actor = self.ctx.refresh(actor)
        require(actor, "task.manage")
        if not (title or "").strip():
            raise ValidationError("Title is required.", {"title": "Enter a task title."})
        store = self.ctx.store
        with store.transaction():
            volunteer = store.get("users", assigned_to, User)
            if volunteer.role != Role.VOLUNTEER or not volunteer.active or volunteer.site_id != actor.site_id:
                raise ValidationError("Choose an active volunteer from your site.", {"assigned_to": "Invalid volunteer."})
            if order_id:
                order = store.get("orders", order_id, Order)
                check_site(actor, order.site_id)
            task = Task(id=store.next_id("TSK"), site_id=actor.site_id, title=title.strip(),
                        description=description.strip(), assigned_to=assigned_to, order_id=order_id,
                        status=TaskStatus.NOT_STARTED, created_by=actor.id, created_at=self.ctx.stamp(),
                        updated_at=self.ctx.stamp())
            store.put("tasks", task)
            self.ctx.audit.log(actor, "task.created", "task", task.id, {"assigned_to": assigned_to})
        return task

    def my_tasks(self, actor: User) -> List[Task]:
        """FR-VTM-02: a volunteer sees only their own tasks."""
        actor = self.ctx.refresh(actor)
        require(actor, "task.view_own")
        return sorted(self.ctx.store.find("tasks", Task, lambda t: t.assigned_to == actor.id), key=lambda t: t.id)

    def list_tasks(self, actor: User, status: str = None) -> List[Task]:
        actor = self.ctx.refresh(actor)
        require(actor, "task.view_all")
        site = resolve_site(actor)
        return sorted(self.ctx.store.find(
            "tasks", Task, lambda t: (not site or t.site_id == site) and (not status or t.status == status)),
            key=lambda t: t.id)

    def update_status(self, actor: User, task_id: str, new_status: str) -> Task:
        """FR-VTM-03: the assigned volunteer moves the task to In Progress / Completed."""
        actor = self.ctx.refresh(actor)
        require(actor, "task.update_status")
        if new_status not in (TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED):
            raise ValidationError("Invalid status.", {"status": "Choose in_progress or completed."})
        store = self.ctx.store
        with store.transaction():
            task = store.get("tasks", task_id, Task)
            if task.assigned_to != actor.id:
                raise PermissionDenied("This task is not assigned to you.")
            if new_status not in ALLOWED_TRANSITIONS[task.status]:
                raise ConflictError(f"A task that is {task.status} cannot become {new_status}.")
            task.status, task.updated_at = new_status, self.ctx.stamp()
            store.put("tasks", task)
            self.ctx.audit.log(actor, "task.status_changed", "task", task.id, {"new": new_status})
        return task

    # ---------- issue reports ----------
    def submit_issue(self, actor: User, issue_type: str, note: str, inventory_id: str = None, order_id: str = None) -> IssueReport:
        """FR-VTM-04: report damaged food / missing stock / incomplete order and flag it for staff."""
        actor = self.ctx.refresh(actor)
        require(actor, "issue.submit")
        errors = {}
        if issue_type not in IssueType.ALL:
            errors["issue_type"] = "Choose damaged_food, missing_stock or incomplete_order."
        if not (note or "").strip():
            errors["note"] = "Describe the problem."
        if not inventory_id and not order_id:
            errors["target"] = "Select the item or order affected."
        if errors:
            raise ValidationError("Please correct the highlighted fields.", errors)
        store = self.ctx.store
        with store.transaction():
            if order_id:
                order = store.get("orders", order_id, Order)
                check_site(actor, order.site_id)
                if not any(t.order_id == order_id and t.assigned_to == actor.id for t in store.find("tasks", Task)):
                    raise PermissionDenied("You are not assigned to this order.")
                order.flagged = True
                store.put("orders", order)
            if inventory_id:
                item = store.get("inventory", inventory_id, InventoryItem)
                check_site(actor, item.site_id)
                item.flagged = True
                store.put("inventory", item)
            issue = IssueReport(id=store.next_id("ISS"), site_id=actor.site_id, reporter_id=actor.id,
                                issue_type=issue_type, note=note.strip(), inventory_id=inventory_id,
                                order_id=order_id, created_at=self.ctx.stamp())
            store.put("issues", issue)
            self.ctx.audit.log(actor, "issue.submitted", "issue", issue.id, {"type": issue_type})
        return issue

    def list_issues(self, actor: User, status: str = "open") -> List[IssueReport]:
        actor = self.ctx.refresh(actor)
        require(actor, "issue.review")
        return sorted(self.ctx.store.find(
            "issues", IssueReport, lambda i: i.site_id == actor.site_id and (not status or i.status == status)),
            key=lambda i: i.id)

    def review_issue(self, actor: User, issue_id: str) -> IssueReport:
        """Staff review an issue; the item/order flag is cleared when no other open issue refers to it."""
        actor = self.ctx.refresh(actor)
        require(actor, "issue.review")
        store = self.ctx.store
        with store.transaction():
            issue = store.get("issues", issue_id, IssueReport)
            check_site(actor, issue.site_id)
            if issue.status != "open":
                raise ConflictError("This issue was already reviewed.")
            issue.status, issue.reviewed_by = "reviewed", actor.id
            store.put("issues", issue)
            others = [i for i in store.find("issues", IssueReport) if i.status == "open"]
            if issue.inventory_id and not any(i.inventory_id == issue.inventory_id for i in others):
                item = store.get("inventory", issue.inventory_id, InventoryItem)
                item.flagged = False
                store.put("inventory", item)
            if issue.order_id and not any(i.order_id == issue.order_id for i in others):
                order = store.get("orders", issue.order_id, Order)
                order.flagged = False
                store.put("orders", order)
            self.ctx.audit.log(actor, "issue.reviewed", "issue", issue.id)
        return issue
