import os
import unittest

from . import (__version__, exceptions, loader, parser,
                        report, runner, utils)
from . import  logger
import json


class HttpRunner(object):
    """ Developer Interface: Main Interface
        Usage:

            from httprunner.api import HttpRunner
            runner = HttpRunner(
                failfast=True,
                save_tests=True,
                log_level="INFO",
                log_file="test.log"
            )
            summary = runner.run(path_or_tests)

    """

    def __init__(self, failfast=False, save_tests=False, log_level="INFO", log_file=None):
        """ initialize HttpRunner.

        Args:
            failfast (bool): stop the test run on the first error or failure.
            save_tests (bool): save loaded/parsed tests to JSON file.
            log_level (str): logging level.
            log_file (str): log file path.

        """
        logger.setup_logger(log_level, log_file)

        self.exception_stage = "initialize HttpRunner()"
        kwargs = {
            "failfast": failfast,
            "resultclass": report.HtmlTestResult
        }
        self.unittest_runner = unittest.TextTestRunner(**kwargs)
        self.test_loader = unittest.TestLoader()
        self.save_tests = save_tests
        self._summary = None
        self.project_working_directory = None

    def _add_tests(self, testcases):
        """ initialize testcase with Runner() and add to test suite.

        Args:
            testcases (list): testcases list.

        Returns:
            unittest.TestSuite()

        """
        def _add_test(test_runner, test_dict):
            """ add test to testcase.
            """
            def test(self):
                try:
                    test_runner.run_test(test_dict)
                except exceptions.MyBaseFailure as ex:
                    self.fail(str(ex))
                finally:
                    self.meta_datas = test_runner.meta_datas

            if "config" in test_dict:
                # run nested testcase
                test.__doc__ = test_dict["config"].get("name")
                variables = test_dict["config"].get("variables", {})
            else:
                # run api test
                test.__doc__ = test_dict.get("name")
                variables = test_dict.get("variables", {})

            if isinstance(test.__doc__, parser.LazyString):
                try:
                    parsed_variables = parser.parse_variables_mapping(variables)
                    test.__doc__ = parser.parse_lazy_data(
                        test.__doc__, parsed_variables
                    )
                except exceptions.VariableNotFound:
                    test.__doc__ = str(test.__doc__)

            return test

        test_suite = unittest.TestSuite()
        for testcase in testcases:
            config = testcase.get("config", {})
            test_runner = runner.Runner(config)
            TestSequense = type('TestSequense', (unittest.TestCase,), {})

            tests = testcase.get("teststeps", [])
            for index, test_dict in enumerate(tests):
                times = test_dict.get("times", 1)
                try:
                    times = int(times)
                except ValueError:
                    raise exceptions.ParamsError(
                        "times should be digit, given: {}".format(times))

                for times_index in range(times):
                    # suppose one testcase should not have more than 9999 steps,
                    # and one step should not run more than 999 times.
                    test_method_name = 'test_{:04}_{:03}'.format(index, times_index)
                    test_method = _add_test(test_runner, test_dict)
                    setattr(TestSequense, test_method_name, test_method)

            loaded_testcase = self.test_loader.loadTestsFromTestCase(TestSequense)
            setattr(loaded_testcase, "config", config)
            setattr(loaded_testcase, "teststeps", tests)
            setattr(loaded_testcase, "runner", test_runner)
            test_suite.addTest(loaded_testcase)

        return test_suite

    def _run_suite(self, test_suite):
        """ run tests in test_suite

        Args:
            test_suite: unittest.TestSuite()

        Returns:
            list: tests_results

        """
        tests_results = []

        for testcase in test_suite:
            testcase_name = testcase.config.get("name")
            logger.log_info("Start to run testcase: {}".format(testcase_name))

            result = self.unittest_runner.run(testcase)
            if result.wasSuccessful():
                tests_results.append((testcase, result))
            else:
                tests_results.insert(0, (testcase, result))

        return tests_results

    def _aggregate2(self, tests_results):
        """ aggregate results

        Args:
            tests_results (list): list of (testcase, result)

        """
        summary = {
            "success": True,
            "stat": {
                "testcases": {
                    "total": len(tests_results),
                    "success": 0,
                    "fail": 0
                },
                "teststeps": {}
            },
            "time": {},
            "platform": report.get_platform(),
            "details": []
        }

        for tests_result in tests_results:
            testcase, result = tests_result
            testcase_summary = report.get_summary(result)

            if testcase_summary["success"]:
                summary["stat"]["testcases"]["success"] += 1
            else:
                summary["stat"]["testcases"]["fail"] += 1

            summary["success"] &= testcase_summary["success"]
            testcase_summary["name"] = testcase.config.get("name")
            testcase_summary["in_out"] = utils.get_testcase_io(testcase)

            report.aggregate_stat(summary["stat"]["teststeps"], testcase_summary["stat"])
            report.aggregate_stat(summary["time"], testcase_summary["time"])

            summary["details"].append(testcase_summary)

        return summary

    def _aggregate(self, tests_results):
        """ aggregate results

        Args:
            tests_results (list): list of (testcase, result)

        """
        summary = {
            "success": True,
            "stat": {},
            "time": {},
            "platform": report.get_platform(),
            "details": []
        }

        for tests_result in tests_results:
            testcase, result = tests_result

            testcase_summary = report.get_summary(result)
            summary["success"] &= testcase_summary["success"]
            testcase_summary["name"] = testcase.config.get("name")
            testcase_summary["base_url"] = testcase.config.get("request", {}).get("base_url", "")

            in_out = utils.get_testcase_io(testcase)
            self.print_io(in_out)
            testcase_summary["in_out"] = in_out

            report.aggregate_stat(summary["stat"], testcase_summary["stat"])
            report.aggregate_stat(summary["time"], testcase_summary["time"])
            for index,each in enumerate(testcase_summary['records']):
                meta_data = each["meta_datas"]["data"][0]
                testcase_summary['records'][index]['meta_data'] = meta_data
                del testcase_summary['records'][index]['meta_datas']



            summary["details"].append(testcase_summary)
        # print (summary["details"])
        return summary

    def print_io(self,in_out):
        """ print input(variables) and output.

        Args:
            in_out (dict): input(variables) and output mapping.

        Examples:
            >>> in_out = {
                    "in": {
                        "var_a": "hello",
                        "var_b": "world"
                    },
                    "out": {
                        "status_code": 500
                    }
                }
            >>> print_io(in_out)
            ================== Variables & Output ==================
            Type   | Variable         :  Value
            ------ | ---------------- :  ---------------------------
            Var    | var_a            :  hello
            Var    | var_b            :  world

            Out    | status_code      :  500
            --------------------------------------------------------

        """
        content_format = "{:<6} | {:<16} :  {:<}\n"
        content = "\n================== Variables & Output ==================\n"
        content += content_format.format("Type", "Variable", "Value")
        content += content_format.format("-" * 6, "-" * 16, "-" * 27)

        def prepare_content(var_type, in_out):
            content = ""
            for variable, value in in_out.items():
                if isinstance(value, tuple):
                    continue
                elif isinstance(value, (dict, list)):

                    value = json.dumps(value)


                content += content_format.format(var_type, variable, value)

            return content

        _in = in_out["in"]
        _out = in_out["out"]

        content += prepare_content("Var", _in)
        content += "\n"
        content += prepare_content("Out", _out)
        content += "-" * 56 + "\n"

        logger.log_debug(content)

    def run_tests(self, tests_mapping):
        """ run testcase/testsuite data
        """

        project_mapping = tests_mapping.get("project_mapping", {})
        self.project_working_directory = project_mapping.get("PWD", os.getcwd())

        if self.save_tests:
            utils.dump_logs(tests_mapping, project_mapping, "loaded")

        # parse tests
        self.exception_stage = "parse tests"
        parsed_testcases = parser.parse_tests(tests_mapping)
        if self.save_tests:
            utils.dump_logs(parsed_testcases, project_mapping, "parsed")

        # add tests to test suite
        self.exception_stage = "add tests to test suite"
        test_suite = self._add_tests(parsed_testcases)

        # run test suite
        self.exception_stage = "run test suite"
        results = self._run_suite(test_suite)

        # aggregate results
        self.exception_stage = "aggregate results"
        self._summary = self._aggregate(results)





        # generate html report
        # self.exception_stage = "generate html report"
        # report.stringify_summary(self._summary)

        # if self.save_tests:
        #     utils.dump_logs(self._summary, project_mapping, "summary")


        return self._summary

    def get_vars_out(self):
        """ get variables and output
        Returns:
            list: list of variables and output.
                if tests are parameterized, list items are corresponded to parameters.

                [
                    {
                        "in": {
                            "user1": "leo"
                        },
                        "out": {
                            "out1": "out_value_1"
                        }
                    },
                    {...}
                ]

            None: returns None if tests not started or finished or corrupted.

        """
        if not self._summary:
            return None

        return [
            summary["in_out"]
            for summary in self._summary["details"]
        ]

    def run_path(self, path, dot_env_path=None, mapping=None):
        """ run testcase/testsuite file or folder.

        Args:
            path (str): testcase/testsuite file/foler path.
            dot_env_path (str): specified .env file path.
            mapping (dict): if mapping is specified, it will override variables in config block.

        Returns:
            dict: result summary

        """
        # load tests
        self.exception_stage = "load tests"
        tests_mapping = loader.load_cases(path, dot_env_path)

        if mapping:
            tests_mapping["project_mapping"]["variables"] = mapping

        return self.run_tests(tests_mapping)

    def run(self, path_or_tests, dot_env_path=None, mapping=None):
        """ main interface.

        Args:
            path_or_tests:
                str: testcase/testsuite file/foler path
                dict: valid testcase/testsuite data

        Returns:
            dict: result summary

        """
        logger.log_info("HttpRunner version: {}".format(__version__))
        if loader.is_testcase_path(path_or_tests):
            return self.run_path(path_or_tests, dot_env_path, mapping)
        elif loader.is_testcases(path_or_tests):
            return self.run_tests(path_or_tests)
        elif loader.is_api(path_or_tests):
            return self.run_tests(path_or_tests)
        else:
            raise exceptions.ParamsError("Invalid testcase path or testcases: {}".format(path_or_tests))
