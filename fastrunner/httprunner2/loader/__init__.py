"""
HttpRunner loader

- check: validate testcase data structure with JSON schema (TODO)
- locate: locate debugtalk.py, make it's dir as project root path
- load: load testcase files and relevant data, including debugtalk.py, .env, yaml/json api/testcases, csv, etc.
- buildup: assemble loaded content to httprunner testcase/testsuite data structure

"""

from .check import is_testcase_path, is_testcases, validate_json_file,is_api
from .load import load_csv_file, load_builtin_functions
from .buildup import load_cases, load_project_data

__all__ = [
    "is_testcase_path",
    "is_testcases",
    "validate_json_file",
    "load_csv_file",
    "load_builtin_functions",
    "load_project_data",
    "load_cases"
]
