import json
import re

from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import render
from django.utils.decorators import method_decorator
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from FasterRunner import pagination
from fastrunner import models, serializers
from fastrunner.utils import response
from fastrunner.utils.decorator import request_log


class ReportView(GenericViewSet):
    """
    报告视图
    """
    queryset = models.Report.objects
    serializer_class = serializers.ReportSerializer
    pagination_class = pagination.MyPageNumberPagination

    def get_authenticators(self):
        # 查看报告详情不需要鉴权
        # self.request.path = '/api/fastrunner/reports/3053/'
        pattern = re.compile(r'/api/fastrunner/reports/\d+/')
        if self.request.method == 'GET' and re.search(pattern, self.request.path) is not None:
            return []
        return super().get_authenticators()

    @method_decorator(request_log(level='DEBUG'))
    def list(self, request):
        """报告列表
        """

        project = request.query_params['project']
        search = request.query_params["search"]
        report_type = request.query_params["reportType"]
        report_status = request.query_params["reportStatus"]
        only_me = request.query_params["onlyMe"]

        queryset = self.get_queryset().filter(project__id=project).order_by('-update_time')

        # 前端传过来是小写的字符串，不是python的True
        if only_me == 'true':
            queryset = queryset.filter(creator=request.user)

        if search != '':
            queryset = queryset.filter(name__contains=search)

        if report_type != '':
            queryset = queryset.filter(type=report_type)

        if report_status != '':
            queryset = queryset.filter(status=report_status)

        page_report = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page_report, many=True)
        return self.get_paginated_response(serializer.data)

    @method_decorator(request_log(level='INFO'))
    def delete(self, request, **kwargs):
        """删除报告
        """
        """
           删除一个报告pk
           删除多个
           [{
               id:int
           }]
        """
        try:
            if kwargs.get('pk'):  # 单个删除
                models.Report.objects.get(id=kwargs['pk']).delete()
            else:
                for content in request.data:
                    models.Report.objects.get(id=content['id']).delete()

        except ObjectDoesNotExist:
            return Response(response.REPORT_NOT_EXISTS)

        return Response(response.REPORT_DEL_SUCCESS)

    @method_decorator(request_log(level='INFO'))
    def look(self, request, **kwargs):
        """查看报告
        """
        pk = kwargs["pk"]
        report = models.Report.objects.get(id=pk)
        report_detail = models.ReportDetail.objects.get(report_id=pk)
        summary = json.loads(report.summary, encoding="utf-8")


        summary['details'] = str(report_detail.summary_detail).replace('Markup','').replace('\\n','').replace(" ","").replace("&#34;","\"")
        summary['details'] = eval(summary['details'])
        print (summary)

        summary["html_report_name"] = report.name
        # return render_to_response('report_template.html', summary)

        return render(request,template_name='report_template.html',context=summary)

    def download(self, request, **kwargs):
        """下载报告
        """
        pass
