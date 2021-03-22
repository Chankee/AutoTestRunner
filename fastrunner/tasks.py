import datetime

from celery import shared_task
from django.core.exceptions import ObjectDoesNotExist
from fastrunner import models
from fastrunner.utils.loader import save_summary, debug_suite, debug_api
from fastrunner.utils.ding_message import DingMessage
from fastrunner.utils import lark_message


@shared_task
def async_debug_api(test_case, project, name=None, config=None, save=False,log_file=None):
    """异步执行api
    """
    summary = debug_api(test_case, project, name=f'批量运行{len(test_case)}条API', config=config,
                        save=save,
                        log_file=log_file)

    save_summary(name, summary, project, api_type=1)


@shared_task
def async_debug_suite(suite, project, obj, report, config):
    """异步执行suite
    """
    summary = debug_suite(suite, project, obj, config=config, save=False)
    save_summary(report, summary, project)


@shared_task
def schedule_debug_suite(*args, **kwargs):
    """定时任务
    """

    project = kwargs["project"]
    suite = []
    test_sets = []
    config_list = []
    for pk in args:
        try:
            name = models.Case.objects.get(id=pk).name
            suite.append({
                "name": name,
                "id": pk
            })
        except ObjectDoesNotExist:
            pass

    for content in suite:
        test_list = models.CaseStep.objects. \
            filter(case__id=content["id"]).order_by("step").values("body")

        testcase_list = []
        config = None
        for content in test_list:
            body = eval(content["body"])
            if "base_url" in body["request"].keys():
                config = eval(
                    models.Config.objects.get(
                        name=body["name"],
                        project__id=project).body)
                continue
            testcase_list.append(body)
        config_list.append(config)
        test_sets.append(testcase_list)

    summary = debug_suite(test_sets, project, suite, config_list, save=False)
    task_name = kwargs["task_name"]

    if kwargs.get('run_type') == 'deploy':
        task_name = '部署_' + task_name
        run_type = 'deploy'
        report_type = 4
    else:
        run_type = 'auto'
        report_type = 3

    save_summary(task_name, summary, project, type=report_type)

    strategy = kwargs["strategy"]
    if strategy == '始终发送' or (
            strategy == '仅失败发送' and summary['stat']['failures'] > 0):
        # ding_message = DingMessage(run_type)
        # ding_message.send_ding_msg(summary, report_name=task_name)
        webhook = kwargs.get("webhook", "")
        if webhook:
            summary["task_name"] = task_name
            lark_message.send_message(summary=summary, webhook=webhook)
