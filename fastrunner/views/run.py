from loguru import logger
import datetime

from django.core.exceptions import ObjectDoesNotExist
from rest_framework.decorators import api_view, authentication_classes
from fastrunner.utils import loader, response
from fastrunner import tasks
from rest_framework.response import Response
from fastrunner.utils.decorator import request_log
from fastrunner.utils.ding_message import DingMessage
from fastrunner.utils.host import *
from fastrunner.utils.parser import Format
from fastrunner import models
from FasterRunner.settings.dev import log_file
import os

"""运行方式
"""

config_err = {
    "success": False,
    "msg": "指定的配置文件不存在",
    "code": "9999"
}

def delfile(logger_file):
    '''
    删除日志文件
    '''
    abs_path, file_name = os.path.split(logger_file)
    del_file = os.listdir(abs_path)

    for file in del_file:
        if file == 'debug.log' or file == 'run.log' or file == file_name:
            pass
        else:
            filePath = os.path.join(abs_path, file)
            if os.path.isfile(filePath):
                os.remove(filePath)
                logger.info(f'--删除日志文件--{file}')

@api_view(['POST'])
@request_log(level='INFO')
def run_api(request):
    """ run api by body
    """
    name = request.data.pop('config')
    host = request.data.pop("host")
    timestamp = request.data.pop("timestamp")

    api = Format(request.data)
    api.parse()

    logger_file = log_file+'/' + str(timestamp) + '.log'

    config = None
    if name != '请选择':
        try:
            config = eval(models.Config.objects.get(name=name, project__id=api.project).body)

        except ObjectDoesNotExist:
            logger.error("指定配置文件不存在:{name}".format(name=name))
            return Response(config_err)

    if host != "请选择":
        host = models.HostIP.objects.get(name=host, project__id=api.project).value.splitlines()
        api.testcase = parse_host(host, api.testcase)
    try:
        summary = loader.debug_api(api.testcase, api.project, name=api.name, config=parse_host(host, config), user=request.user,log_file=logger_file)
        if summary is None:
            with open(logger_file, 'r') as r:
                msg = r.readlines()
            summary = msg
            return Response({"error":summary})
        return Response(summary)
    except Exception as e:
        return Response({"error":"404"})
    finally:
        '''删除调试脚本的日志文件'''
        delfile(logger_file)





@api_view(['GET'])
@request_log(level='INFO')
def run_api_pk(request, **kwargs):
    """run api by pk and config
    """
    host = request.query_params["host"]
    api = models.API.objects.get(id=kwargs['pk'])
    name = request.query_params["config"]
    timestamp = request.query_params["timestamp"]

    config = None if name == '请选择' else eval(models.Config.objects.get(name=name, project=api.project).body)

    logger_file = log_file + '/' + str(timestamp) + '.log'

    test_case = eval(api.body)
    if host == '请选择' and "base_url" not in test_case["request"].keys() and "http" not in test_case["request"]["url"]:
        return Response({"status": "500", "tips": "请完善请求URL"})
    if host != "请选择":
        host = models.HostIP.objects.get(name=host, project=api.project).value.splitlines()
        test_case = parse_host(host, test_case)

    try:
        summary = loader.debug_api(test_case, api.project.id, name=api.name, config=parse_host(host, config), user=request.user,log_file=logger_file)
        if summary is None:
            with open(logger_file, 'r') as r:
                msg = r.readlines()
            summary = msg
            return Response({"error": summary})
        return Response(summary)
    except Exception as e:
        return Response({"error": "404"})

    finally:
        '''删除调试脚本的日志文件'''
        delfile(logger_file)




def auto_run_api_pk(**kwargs):
    """run api by pk and config
    """
    id = kwargs['id']
    env = kwargs['config']
    config_name = 'rig_prod' if env == 1 else 'rig_test'
    api = models.API.objects.get(id=id)
    config = eval(models.Config.objects.get(name=config_name, project=api.project).body)
    test_case = eval(api.body)

    summary = loader.debug_api(test_case, api.project.id, config=config)
    api_request = summary['details'][0]['records'][0]['meta_data']['request']
    api_response = summary['details'][0]['records'][0]['meta_data']['response']

    # API执行成功,设置tag为自动运行成功
    if summary['stat']['failures'] == 0 and summary['stat']['errors'] == 0:
        models.API.objects.filter(id=id).update(tag=3)
        return 'success'
    elif summary['stat']['failures'] == 1:
        # models.API.objects.filter(id=id).update(tag=2)
        return 'fail'


def update_auto_case_step(**kwargs):
    """
    {'name': '查询关联的商品推荐列表-小程序需签名-200014-生产',
    'body': {'name': '查询关联的商品推荐列表-小程序需签名-200014-生产',
    'rig_id': 200014, 'times': 1,
    'request': {'url': '/wxmp/mall/goods/detail/getRecommendGoodsList',
    'method': 'GET', 'verify': False, 'headers': {'wb-token': '$wb_token'},
    'params': {'goodsCode': '42470'}}, 'desc': {'header': {'wb-token': '用户登陆token'}, 'data': {}, 'files': {},
    'params': {'goodsCode': '商品编码'}, 'variables': {'auth_type': '认证类型', 'rpc_Group': 'RPC服务组',
    'rpc_Interface': '后端服务接口', 'params_type': '入参数形式', 'author': '作者'}, 'extract': {}},
    'validate': [{'equals': ['content.info.error', 0]}], 'variables': [{'auth_type': 5},
    {'rpc_Group': 'wbiao.seller.prod'}, {'rpc_Interface': 'cn.wbiao.seller.api.GoodsDetailService'},
    {'params_type': 'Key_Value'}, {'author': 'xuqirong'}], 'setup_hooks': ['${get_sign($request,$auth_type)}']},
    'url': '/wxmp/mall/goods/detail/getRecommendGoodsList', 'method': 'GET', 'step': 5}
    :param kwargs:
    :return:
    """
    # 去掉多余字段
    kwargs.pop('project')
    kwargs.pop('rig_id')
    kwargs.pop('relation')

    # 测试环境0,对应97 生产环境1,对应98
    rig_env = kwargs.pop('rig_env')
    case_id = 98 if rig_env == 1 else 97
    # 获取case的长度,+1是因为增加了一个case_step,
    length = models.Case.objects.filter(id=case_id).first().length + 1
    # case的长度也就是case_step的数量
    kwargs['step'] = length
    kwargs['case_id'] = case_id
    case_step_name = kwargs['name']
    # api不存在用例中,就新增,已经存在就更新
    is_case_step_name = models.CaseStep.objects.filter(case_id=case_id).filter(name=case_step_name)
    if len(is_case_step_name) == 0:
        models.Case.objects.filter(id=case_id).update(length=length, update_time=datetime.datetime.now())
        models.CaseStep.objects.create(**kwargs)
    else:
        is_case_step_name.update(update_time=datetime.datetime.now(), **kwargs)


@api_view(['POST'])
@request_log(level='INFO')
def run_api_tree(request):
    """run api by tree
    {
        project: int
        relation: list
        name: str
        async: bool
        host: str
    }
    """
    # order by id default
    host = request.data["host"]
    project = request.data['project']
    relation = request.data["relation"]
    back_async = request.data["async"]
    name = request.data["name"]
    config = request.data["config"]


    timestamp = request.data["timestamp"]
    logger_file = log_file + '/' + str(timestamp) + '.log'

    config = None if config == '请选择' else eval(models.Config.objects.get(name=config, project__id=project).body)
    test_case = []

    if host != "请选择":
        host = models.HostIP.objects.get(name=host, project=project).value.splitlines()

    for relation_id in relation:
        api = models.API.objects.filter(project__id=project, relation=relation_id, delete=0).order_by('id').values(
            'body')
        for content in api:
            api = eval(content['body'])
            if host == '请选择' and "base_url" not in api["request"].keys() and "http" not in api["request"][
                "url"]:
                return Response({"status": "500", "tips": "请完善请求URL"})
            test_case.append(parse_host(host, api))

    if back_async:
        tasks.async_debug_api.delay(test_case, project, name, config=parse_host(host, config),log_file=logger_file)
        summary = loader.TEST_NOT_EXISTS
        summary["msg"] = "接口运行中，请稍后查看报告"
        return Response(summary)
    else:
        try:
            summary = loader.debug_api(test_case, project, name=f'批量运行{len(test_case)}条API', config=parse_host(host, config),
                                       user=request.user,
                                       log_file=logger_file)
            if summary is None:
                with open(logger_file, 'r') as r:
                    msg = r.readlines()
                summary = msg
                return Response({"error":summary})
            return Response(summary)
        except Exception as e:
            return Response({"error": "404"})
        finally:
            '''删除调试脚本的日志文件'''
            delfile(logger_file)




@api_view(["POST"])
@request_log(level='INFO')
def run_testsuite(request):
    """debug testsuite
    {
        name: str,
        body: dict
        host: str
    }
    """
    body = request.data["body"]
    project = request.data["project"]
    name = request.data["name"]
    host = request.data["host"]

    test_case = []
    config = None

    timestamp = request.data.pop("timestamp")

    logger_file = log_file+'/' + str(timestamp) + '.log'

    if host != "请选择":
        host = models.HostIP.objects.get(name=host, project=project).value.splitlines()

    for test in body:
        test = loader.load_test(test, project=project)
        if "base_url" in test["request"].keys():
            config = test
            continue

        test_case.append(parse_host(host, test))

    try:
        summary = loader.debug_api(test_case, project, name=name, config=config, user=request.user,log_file=logger_file)
        if summary is None:
            with open(logger_file, 'r') as r:
                msg = r.readlines()
            summary = msg
            return Response({"error": summary})
        return Response(summary)
    except Exception as e:
        return Response({"error": "404"})
    finally:
        '''删除调试脚本的日志文件'''
        delfile(logger_file)



@api_view(["GET"])
@request_log(level='INFO')
def run_testsuite_pk(request, **kwargs):
    """run testsuite by pk
        {
            project: int,
            name: str,
            host: str
        }
    """
    pk = kwargs["pk"]

    test_list = models.CaseStep.objects. \
        filter(case__id=pk).order_by("step").values("body")

    project = request.query_params["project"]
    name = request.query_params["name"]
    host = request.query_params["host"]
    back_async = request.query_params.get("async", False)


    timestamp = request.query_params["timestamp"]
    logger_file = log_file + '/' + str(timestamp) + '.log'

    test_case = []
    config = None


    if host != "请选择":
        host = models.HostIP.objects.get(name=host, project=project).value.splitlines()

    for content in test_list:
        body = eval(content["body"])

        if "base_url" in body["request"].keys():
            config = eval(models.Config.objects.get(name=body["name"], project__id=project).body)
            continue
        if host == '请选择' and "base_url" not in body["request"].keys() and "http" not in body["request"]["url"]:
            return Response({"status":"500","tips":"请完善请求URL"})
        test_case.append(parse_host_suite_tree(host, body))

    suite = list(models.Case.objects.filter(id=pk).order_by('id').values('id', 'name'))


    if back_async:
        tasks.async_debug_api.delay(test_case, project, name=name, config=parse_host_suite_tree(host, config))
        summary = response.TASK_RUN_SUCCESS

    else:
        try:
            summary = loader.debug_suite_tree_pk(test_case,project, suite, config=config, save=True, user='',log_file=logger_file)
            if summary is None:
                with open(logger_file, 'r') as r:
                    msg = r.readlines()
                summary = msg
                return Response({"error":summary})
            return Response(summary)
        except Exception as e:
            return Response({"error": "404"})
        finally:
            '''删除调试脚本的日志文件'''
            delfile(logger_file)

@api_view(["GET"])
@request_log(level='INFO')
def run_testsuite_pk_origin(request, **kwargs):
    """run testsuite by pk
        {
            project: int,
            name: str,
            host: str
        }
    """
    pk = kwargs["pk"]

    test_list = models.CaseStep.objects. \
        filter(case__id=pk).order_by("step").values("body")

    project = request.query_params["project"]
    name = request.query_params["name"]
    host = request.query_params["host"]
    back_async = request.query_params.get("async", False)


    test_case = []
    config = None

    if host != "请选择":
        host = models.HostIP.objects.get(name=host, project=project).value.splitlines()

    for content in test_list:
        body = eval(content["body"])

        if "base_url" in body["request"].keys():
            config = eval(models.Config.objects.get(name=body["name"], project__id=project).body)
            continue

        test_case.append(parse_host(host, body))

    if back_async:
        tasks.async_debug_api.delay(test_case, project, name=name, config=parse_host(host, config))
        summary = response.TASK_RUN_SUCCESS

    else:
        summary = loader.debug_api(test_case, project, name=name, config=parse_host(host, config), user=request.user)

    return Response(summary)


@api_view(['POST'])
@request_log(level='INFO')
def run_suite_tree(request):
    """run suite by tree
    {
        project: int
        relation: list
        name: str
        async: bool
        host: str
    }
    """
    # order by id default
    project = request.data['project']
    relation = request.data["relation"]
    back_async = request.data["async"]
    report = request.data["name"]
    host = request.data["host"]
    timestamp = request.data.pop("timestamp")

    logger_file = log_file + '/' + str(timestamp) + '.log'


    if host != "请选择":
        host = models.HostIP.objects.get(name=host, project=project).value.splitlines()



    test_sets = []
    suite_list = []
    config_list = []
    for relation_id in relation:
        suite = list(models.Case.objects.filter(project__id=project,
                                                relation=relation_id).order_by('id').values('id', 'name'))


        for content in suite:
            test_list = models.CaseStep.objects. \
                filter(case__id=content["id"]).order_by("step").values("body")

            testcase_list = []
            config = None
            for content in test_list:
                body = eval(content["body"])
                if "base_url" in body["request"].keys():

                    config = eval(models.Config.objects.get(name=body["name"], project__id=project).body)
                    continue
                if host == '请选择' and "base_url" not in body["request"].keys() and "http" not in body["request"]["url"]:
                    return Response({"status": "500", "tips": "请完善请求URL"})
                testcase_list.append(parse_host_suite_tree(host, body))
            # [[{scripts}, {scripts}], [{scripts}, {scripts}]]
            config_list.append(parse_host_suite_tree(host, config))
            test_sets.append(testcase_list)
            suite_list = suite_list + suite

    if back_async:
        tasks.async_debug_suite.delay(test_sets, project, suite_list, report, config_list)
        summary = loader.TEST_NOT_EXISTS
        summary["msg"] = "用例运行中，请稍后查看报告"
    else:
        try:
            summary = loader.debug_suite_tree(test_sets, project, suite_list, config_list, save=True, user=request.user,log_file=logger_file)
            if summary is None:
                with open(logger_file, 'r') as r:
                    msg = r.readlines()
                summary = msg
                return Response({"error":summary})
            return Response(summary)
        except Exception as e:
            return Response({"error": "404"})
        finally:
            '''删除调试脚本的日志文件'''
            delfile(logger_file)


@api_view(["POST"])
@request_log(level='INFO')
def run_test(request):
    """debug single test
    {
        host: str
        body: dict
        project :int
        config: null or dict
    }
    测试用例集 单个运行api
    """

    body = request.data["body"]
    config = request.data.get("config", None)
    project = request.data["project"]
    host = request.data["host"]
    timestamp = request.data.pop("timestamp")


    logger_file = log_file+'/' + str(timestamp) + '.log'
    if host != "请选择":
        host = models.HostIP.objects.get(name=host, project=project).value.splitlines()


    if config:

        config = eval(models.Config.objects.get(project=project, name=config["name"]).body)

    try:


        summary = loader.debug_api(parse_host(host, loader.load_test(body)), project, name=body.get('name', None),
                               config=config, user=request.user,log_file=logger_file)

        if summary is None:
            with open(logger_file, 'r') as r:
                msg = r.readlines()
            summary = msg
            return Response({"error": summary})
        return Response(summary)
    except Exception as e:

        return Response({"error":"404"})
    finally:
        '''删除调试脚本的日志文件'''
        delfile(logger_file)
        # pass

