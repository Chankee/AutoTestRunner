import copy
import datetime
import functools
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import types
from threading import Thread

from requests import utils
import yaml
from bs4 import BeautifulSoup

from fastrunner.httprunner.api import  HttpRunner
from fastrunner.httprunner import logger, parser
from fastrunner.httprunner.exceptions import FunctionNotFound, VariableNotFound

from requests.cookies import RequestsCookieJar
from requests_toolbelt import MultipartEncoder

from fastrunner import models
from fastrunner.utils.parser import Format
from FasterRunner.settings.base import BASE_DIR

logger.setup_logger('DEBUG')

TEST_NOT_EXISTS = {
    "code": "0102",
    "status": False,
    "msg": "节点下没有接口或者用例集"
}


def is_function(tup):
    """ Takes (name, object) tuple, returns True if it is a function.
    """
    name, item = tup
    return isinstance(item, types.FunctionType)


def is_variable(tup):
    """ Takes (name, object) tuple, returns True if it is a variable.
    """
    name, item = tup
    if callable(item):
        # function or class
        return False

    if isinstance(item, types.ModuleType):
        # imported module
        return False

    if name.startswith("_"):
        # private property
        return False

    return True


class FileLoader(object):

    @staticmethod
    def dump_yaml_file(yaml_file, data):
        """ dump yaml file
        """
        with io.open(yaml_file, 'w', encoding='utf-8') as stream:
            yaml.dump(
                data,
                stream,
                indent=4,
                default_flow_style=False,
                encoding='utf-8',
                allow_unicode=True)

    @staticmethod
    def dump_json_file(json_file, data):
        """ dump json file
        """
        with io.open(json_file, 'w', encoding='utf-8') as stream:
            json.dump(
                data, stream, indent=4, separators=(
                    ',', ': '), ensure_ascii=False)

    @staticmethod
    def dump_python_file(python_file, data):
        """dump python file
        """
        with io.open(python_file, 'w', encoding='utf-8') as stream:
            stream.write(data)

    @staticmethod
    def dump_binary_file(binary_file, data):
        """dump file
        """
        with io.open(binary_file, 'wb') as stream:
            stream.write(data)

    @staticmethod
    def load_python_module(file_path):
        """ load python module.

        Args:
            file_path: python path

        Returns:
            dict: variables and functions mapping for specified python module

                {
                    "variables": {},
                    "functions": {}
                }

        """
        debugtalk_module = {
            "variables": {},
            "functions": {}
        }

        sys.path.insert(0, file_path)
        module = importlib.import_module("debugtalk")
        # 修复重载bug
        importlib.reload(module)
        sys.path.pop(0)

        for name, item in vars(module).items():
            if is_function((name, item)):
                debugtalk_module["functions"][name] = item
            elif is_variable((name, item)):
                if isinstance(item, tuple):
                    continue
                debugtalk_module["variables"][name] = item
            else:
                pass

        return debugtalk_module


def parse_validate_and_extract(list_of_dict: list, variables_mapping: dict, functions_mapping, api_variables: list):
    """
    Args:
        list_of_dict (list)
        variables_mapping (dict): variables mapping.
        functions_mapping (dict): functions mapping.
        api_variables: (list)
    Returns:
        引用传参，直接修改dict的内容，不需要返回
    """

    # 获取api中所有变量的key
    api_variables_key = []
    for variable in api_variables:
        api_variables_key.extend(list(variable.keys()))

    for index, d in enumerate(list_of_dict):
        is_need_parse = True
        # extract: d是{'k':'v'}, v类型是str
        # validate: d是{'equals': ['v1', 'v2']}， v类型是list
        v = list(d.values())[0]
        try:

            # validate,extract 的值包含了api variable的key中，不需要替换
            for key in api_variables_key:
                if isinstance(v, str):
                    if key in v:
                        is_need_parse = False
                elif isinstance(v, list):
                    # v[1]需要统一转换成str类型，否则v[1]是int类型就会报错
                    if key in str(v[1]):
                        is_need_parse = False

            if is_need_parse is True:
                d = parser.parse_data(d, variables_mapping=variables_mapping, functions_mapping=functions_mapping)
                for k, v in d.items():
                    v = parser.parse_string_functions(v, variables_mapping=variables_mapping,
                                                      functions_mapping=functions_mapping)
                    d[k] = v
                list_of_dict[index] = d
        except (FunctionNotFound, VariableNotFound):
            continue


def parse_cases(testcases, name=None, config=None, project=None):


    testset = {
        "config": {
            "name": name,
            "variables": []
        },
        "teststeps": [
        ],
        "path":'',
        "type":'testcase'
    }


    # 获取当前项目的全局变量
    global_variables = models.Variables.objects.filter(project=project).all().values("key", "value")
    all_config_variables_keys = set().union(*(d.keys() for d in testset["config"].setdefault("variables", [])))
    global_variables_list_of_dict = []
    for item in global_variables:
        if item["key"] not in all_config_variables_keys:
            global_variables_list_of_dict.append({item["key"]: item["value"]})

    # 有variables就直接extend,没有就加一个[],再extend
    # 配置的variables和全局变量重叠,优先使用配置中的variables
    testset["config"].setdefault("variables", []).extend(global_variables_list_of_dict)

    for testcase in testcases:

        each_test = {
            'name': '',
            'api':'',
            'api_def': {

            }
        }
        del testcase['desc']

        each_test['name'] =testcase['name']
        del testcase['rig_id']
        for k,v in testcase.items():
            each_test['api_def'][k]=v

        testset['teststeps'].append(each_test)




    return  testset


def parse_tests(testcases, debugtalk, name=None, config=None, project=None):
    """get test case structure
        testcases: list
        config: none or dict
        debugtalk: dict
    """
    pro_map = parse_cases(testcases,debugtalk,name=None,config=None,project=None)
    refs = {
        "env": {},
        "def-api": {},
        "def-testcase": {},
        "debugtalk": debugtalk
    }

    testset = {
        "config": {
            "name": testcases[-1]["name"],
            "variables": []
        },
        "teststeps": testcases,
    }

    if config:
        testset["config"] = config

    if name:
        testset["config"]["name"] = name

    # 获取当前项目的全局变量
    global_variables = models.Variables.objects.filter(project=project).all().values("key", "value")
    all_config_variables_keys = set().union(*(d.keys() for d in testset["config"].setdefault("variables", [])))
    global_variables_list_of_dict = []
    for item in global_variables:
        if item["key"] not in all_config_variables_keys:
            global_variables_list_of_dict.append({item["key"]: item["value"]})

    # 有variables就直接extend,没有就加一个[],再extend
    # 配置的variables和全局变量重叠,优先使用配置中的variables
    testset["config"].setdefault("variables", []).extend(global_variables_list_of_dict)
    testset["config"]["refs"] = refs

    # 配置中的变量和全局变量合并
    variables_mapping = {}
    if config:
        for variables in config['variables']:
            variables_mapping.update(variables)

    # 驱动代码中的所有函数
    functions_mapping = debugtalk.get('functions', {})



    # 替换extract,validate中的变量和函数，只对value有效，key无效
    for testcase in testcases:
        extract: list = testcase.get('extract', [])
        validate: list = testcase.get('validate', [])
        api_variables: list = testcase.get('variables', [])
        parse_validate_and_extract(extract, variables_mapping, functions_mapping, api_variables)
        parse_validate_and_extract(validate, variables_mapping, functions_mapping, api_variables)

    return  pro_map
    # return testset


def load_debugtalk(project):
    """import debugtalk.py in sys.path and reload
        project: int
    """
    # debugtalk.py
    code = models.Debugtalk.objects.get(project__id=project).code

    # file_path = os.path.join(tempfile.mkdtemp(prefix='FasterRunner'), "debugtalk.py")
    tempfile_path = tempfile.mkdtemp(
        prefix='FasterRunner', dir=os.path.join(
            BASE_DIR, 'tempWorkDir'))
    file_path = os.path.join(tempfile_path, 'debugtalk.py')
    os.chdir(tempfile_path)
    try:
        FileLoader.dump_python_file(file_path, code)
        debugtalk = FileLoader.load_python_module(os.path.dirname(file_path))
        return debugtalk, file_path

    except Exception as e:
        os.chdir(BASE_DIR)
        shutil.rmtree(os.path.dirname(file_path))



def debug_suite_tree_pk(testcases, project, obj, config=None, save=True, user='',log_file=None):
    '''
    运行多条测试用例
    '''
    if len(testcases) == 0:
        return TEST_NOT_EXISTS
    debugtalk = load_debugtalk(project)
    debugtalk_content = debugtalk[0]
    debugtalk_path = debugtalk[1]
    os.chdir(os.path.dirname(debugtalk_path))

    pro_map = {
        "project_mapping": {
            "PWD": "",
            "functions": {},
            "variables": {},
            "env": {}
        },
        "testcases": []
    }
    # 驱动代码中的所有函数
    functions_mapping = debugtalk_content.get('functions', {})
    pro_map['project_mapping']['functions'] = functions_mapping


    try:

        testcases = copy.deepcopy(
                parse_cases(
                    testcases,
                    name=obj[0]['name'],
                    config=None,
                    project=project
                ))
        pro_map['testcases'].append(testcases)


        kwargs = {
            "failfast": False,
            "log_file": log_file
        }

        from fastrunner.httprunner3.api import HttpRunner as HttpRunner3

        runner3 = HttpRunner3(**kwargs)


        runner3.run(pro_map)

        summary = parse_summary(runner3._summary)


        with open(log_file, 'r') as r:
            msg = r.readlines()
        summary['msg'] = msg
        if save:
            save_summary(f"批量运行{len(pro_map['testcases'])}条用例", summary, project, api_type=1, user=user)

        return summary

    except Exception as e:
        raise SyntaxError(str(e))
    finally:
        os.chdir(BASE_DIR)
        shutil.rmtree(os.path.dirname(debugtalk_path))



def debug_suite_tree(suite, project, obj, config=None, save=True, user='',log_file=None):
    '''
    运行多条测试用例
    '''
    if len(suite) == 0:
        return TEST_NOT_EXISTS
    debugtalk = load_debugtalk(project)
    debugtalk_content = debugtalk[0]
    debugtalk_path = debugtalk[1]
    os.chdir(os.path.dirname(debugtalk_path))

    pro_map = {
        "project_mapping": {
            "PWD": "",
            "functions": {},
            "variables": {},
            "env": {}
        },
        "testcases": []
    }
    # 驱动代码中的所有函数
    functions_mapping = debugtalk_content.get('functions', {})
    pro_map['project_mapping']['functions'] = functions_mapping
    try:
        for index in range(len(suite)):
            testcases = copy.deepcopy(
                parse_cases(
                    suite[index],
                    name=obj[index]['name'],
                    config=config[index],
                    project=project
                ))
            pro_map['testcases'].append(testcases)


        kwargs = {
            "failfast": False,
            "log_file": log_file
        }

        from fastrunner.httprunner3.api import HttpRunner as HttpRunner3

        runner3 = HttpRunner3(**kwargs)


        runner3.run(pro_map)

        summary = parse_summary(runner3._summary)


        with open(log_file, 'r') as r:
            msg = r.readlines()
        summary['msg'] = msg
        if save:
            save_summary(f"批量运行{len(pro_map['testcases'])}条用例", summary, project, api_type=1, user=user)

        return summary

    except Exception as e:
        raise SyntaxError(str(e))
    finally:
        os.chdir(BASE_DIR)
        shutil.rmtree(os.path.dirname(debugtalk_path))


def debug_suite(suite, project, obj, config=None, save=True, user='',log_file=None):
    """debug suite
           suite :list
           pk: int
           project: int
    """
    if len(suite) == 0:
        return TEST_NOT_EXISTS

    debugtalk = load_debugtalk(project)
    debugtalk_content = debugtalk[0]
    debugtalk_path = debugtalk[1]
    os.chdir(os.path.dirname(debugtalk_path))
    test_sets = []


    '''
    try:
        for index in range(len(suite)):
            # copy.deepcopy 修复引用bug
            # testcases = copy.deepcopy(parse_tests(suite[index], debugtalk, name=obj[index]['name'], config=config[index]))
            testcases = copy.deepcopy(
                parse_tests(
                    suite[index],
                    debugtalk_content,
                    name=obj[index]['name'],
                    config=config[index],
                    project=project
                ))
            test_sets.append(testcases)

        kwargs = {
            "failfast": False
        }
        

        runner = HttpRunner(**kwargs)
        runner.run(test_sets)
        summary = parse_summary(runner.summary)

        if save:
            save_summary(f"批量运行{len(test_sets)}条用例", summary, project, type=1, user=user)
        return summary
    '''
    try:
        # for index in range(len(suite)):
            # copy.deepcopy 修复引用bug
            # testcases = copy.deepcopy(parse_tests(suite[index], debugtalk, name=obj[index]['name'], config=config[index]))
        testcases = copy.deepcopy(
                parse_tests(
                    suite,
                    debugtalk_content,
                    name=None,
                    config=config,
                    project=project
                ))
            # test_sets.append(testcases)

        print (testcases)
        kwargs = {
            "failfast": False,
            "log_file": log_file
        }

        from  fastrunner.httprunner3.api import HttpRunner as HttpRunner3

        runner3 = HttpRunner3(**kwargs)

        runner3.run(test_sets)

        summary = parse_summary(runner3._summary)
        if save:
            save_summary(f"批量运行{len(test_sets)}条用例", summary, project, type=1, user=user)
        return summary
    except Exception as e:
        raise SyntaxError(str(e))
    finally:
        os.chdir(BASE_DIR)
        shutil.rmtree(os.path.dirname(debugtalk_path))


def debug_api(api, project, name=None, config=None, save=True, user='',log_file=None):
    """debug api
        api :dict or list
        project: int
    """

    print ('-----zhixing')
    if len(api) == 0:
        return TEST_NOT_EXISTS

    # testcases
    if isinstance(api, dict):
        """
        httprunner scripts or teststeps
        """
        api = [api]


    # 删除api的描述信息
    for each_api in api:
        each_api.pop('desc')

    # 参数化过滤,只加载api中调用到的参数
    if config and config.get('parameters'):
        api_params = []
        for item in api:
            params = item['request'].get('params') or item['request'].get('json')
            for v in params.values():
                if type(v) == list:
                    api_params.extend(v)
                else:
                    api_params.append(v)
        parameters = []
        for index, dic in enumerate(config['parameters']):
            for key in dic.keys():
                # key可能是key-key1这种模式,所以需要分割
                for i in key.split('-'):
                    if '$' + i in api_params:
                        parameters.append(dic)
        config['parameters'] = parameters

    debugtalk = load_debugtalk(project)
    debugtalk_content = debugtalk[0]
    debugtalk_path = debugtalk[1]
    os.chdir(os.path.dirname(debugtalk_path))


    '''
    try:
        # testcase_list = [parse_tests(api, load_debugtalk(project), name=name, config=config)]
        testcase_list =parse_tests(
                api,
                debugtalk_content,
                name=name,
                config=config,
                project=project)

        print ('-----test_list',testcase_list)
        kwargs = {
            "failfast": False
        }

        runner = HttpRunner(**kwargs)
        runner.run(testcase_list)
        print ('--------------------runner.summary------------',runner.summary)
        summary = parse_summary_1(runner.summary)


        if save:
            save_summary(name, summary, project, type=1, user=user)
        return summary
    except Exception as e:
        raise SyntaxError(str(e))
    finally:
        os.chdir(BASE_DIR)
        shutil.rmtree(os.path.dirname(debugtalk_path))
    
    '''
    try:
        # testcase_list = [parse_tests(api, load_debugtalk(project), name=name, config=config)]
        testcase_list = parse_api(
            api,
            debugtalk_content,
            name=name,
            config=config,
            project=project)

        kwargs = {
            "failfast": False,
            "log_file":log_file
        }


        from  fastrunner.httprunner3.api import HttpRunner as HttpRunner3

        runner3 = HttpRunner3(**kwargs)


        runner3.run(testcase_list)




        # summary = runner3._summary
        summary = parse_summary(runner3._summary)
        with open(log_file,'r') as r:
            msg = r.readlines()
        summary['msg'] =msg



        if save:
            save_summary(name, summary, project, api_type=1, user=user)
        return summary
    except Exception as e:
       print ('-----debug_api-----',e)
    finally:
        os.chdir(BASE_DIR)
        shutil.rmtree(os.path.dirname(debugtalk_path))



def parse_api(api,debugtalk, name=None, config=None, project=None):
    '''
    对 单步调试API 进行解析
    '''

    pro_map = {
        "project_mapping": {
            "PWD": "",
            "functions": {},
            "variables": {},
            "env": {}
        },
        "apis": {
            "variables": {},
            "request": {}
        }
    }

    # 驱动代码中的所有函数
    functions_mapping = debugtalk.get('functions', {})
    pro_map['project_mapping']['functions'] = functions_mapping

    # 拼接variable
    dict_variable = {}
    for variable in api[0]["variables"]:
        for key,value in variable.items():
            dict_variable[key]=value

    # pro_map["api"]["variables"].update(dict_variable)

    # 组装请求的api到 project_mapping
    pro_map["apis"] = [ a  for a in api]


    return pro_map

def load_test(test, project=None):
    """
    format testcase
    """

    try:
        format_http = Format(test['newBody'])
        format_http.parse()
        testcase = format_http.testcase

    except KeyError:
        if 'case' in test.keys():
            if test["body"]["method"] == "config":
                case_step = models.Config.objects.get(
                    name=test["body"]["name"], project=project)
            else:
                case_step = models.CaseStep.objects.get(id=test['id'])
        else:
            if test["body"]["method"] == "config":
                case_step = models.Config.objects.get(
                    name=test["body"]["name"], project=project)
            else:
                case_step = models.API.objects.get(id=test['id'])

        testcase = eval(case_step.body)
        name = test['body']['name']

        if case_step.name != name:
            testcase['name'] = name



    return testcase


def back_async(func):
    """异步执行装饰器
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        thread = Thread(target=func, args=args, kwargs=kwargs)
        thread.start()

    return wrapper




def parse_summary(summary):
    """序列化summary
    """

    for detail in summary["details"]:

        for record in detail["records"]:



            for key, value in record["meta_data"]["request"].items():
                if isinstance(value, bytes):
                    record["meta_data"]["request"][key] = value.decode("utf-8")
                if isinstance(value, RequestsCookieJar):
                    record["meta_data"]["request"][key] = utils.dict_from_cookiejar(
                        value)

            for key, value in record["meta_data"]["response"].items():
                if isinstance(value, bytes):
                    record["meta_data"]["response"][key] = value.decode(
                        "utf-8")
                if isinstance(value, RequestsCookieJar):
                    record["meta_data"]["response"][key] = utils.dict_from_cookiejar(
                        value)

            if "text/html" in record["meta_data"]["response"]["content_type"]:
                record["meta_data"]["response"]["content"] = BeautifulSoup(
                    record["meta_data"]["response"]["content"], features="html.parser").prettify()

    return summary
def save_summary(name, summary, project, api_type=2, user=''):
    """保存报告信息
    """
    if "status" in summary.keys():
        return
    if name == "" or name is None:
        name = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # 　删除用不到的属性
    summary['details'][0].pop('in_out')
    # 需要先复制一份,不然会把影响到debug_api返回给前端的报告
    summary = copy.copy(summary)
    summary_detail = summary.pop('details')

    report = models.Report.objects.create(**{
        "project": models.Project.objects.get(id=project),
        "name": name,
        "type": api_type,
        "status": summary['success'],
        "summary": json.dumps(summary, ensure_ascii=False),
        "creator": user
    })
    models.ReportDetail.objects.create(summary_detail=summary_detail, report=report)


@back_async
def async_debug_api(api, project, name, config=None):
    """异步执行api
    """
    summary = debug_api(api, project, save=False, config=config)
    save_summary(name, summary, project)


@back_async
def async_debug_suite(suite, project, report, obj, config=None):
    """异步执行suite
    """
    summary = debug_suite(suite, project, obj, config=config, save=False)
    save_summary(report, summary, project)
