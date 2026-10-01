import os
import unittest
from unittest.mock import patch

os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///:memory:'
os.environ['USER_CONTENT_DIR'] = '/tmp/protracklite-test-user-content'

from sqlalchemy import create_engine, inspect, text
from app.main import ensure_tasks_schema, templates


class TaskColorRemovalTests(unittest.TestCase):
    def test_migration_preserves_tasks_and_can_run_again(self):
        database = create_engine('sqlite+pysqlite:///:memory:')
        with database.begin() as connection:
            connection.execute(text("CREATE TABLE tasks (id INTEGER PRIMARY KEY, name TEXT, start_date DATE, task_color VARCHAR(7) NOT NULL DEFAULT '#22c55e')"))
            connection.execute(text("INSERT INTO tasks (id, name, task_color) VALUES (1, 'Keep this task', '#ef4444')"))
        with patch('app.main.engine', database):
            ensure_tasks_schema()
            ensure_tasks_schema()
        self.assertNotIn('task_color', {column['name'] for column in inspect(database).get_columns('tasks')})
        with database.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT id, name FROM tasks')).all(), [(1, 'Keep this task')])
        database.dispose()

    def test_templates_compile_after_removing_controls(self):
        for name in templates.env.list_templates():
            with self.subTest(template=name):
                templates.env.get_template(name)
