import shutil
from . import store

def delete_user_tasks(owner_id: str) -> int:
    tasks = [task for task in store.list_tasks(owner_id, True) if not task["is_demo"] and task["owner_id"] == owner_id]
    for task in tasks:
        store.transition(task["task_id"], "cancelled", error="账号数据已删除")
        store.delete_task(task["task_id"])
        shutil.rmtree(store.task_dir(task["task_id"]), ignore_errors=True)
    return len(tasks)
