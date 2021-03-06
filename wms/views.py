import os
import json
from collections import OrderedDict

from django.conf import settings
from django.http import HttpResponse
from django.contrib.auth import authenticate, login, logout
from django.template.response import TemplateResponse
from django.core import serializers
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import cache_page
from django.views.generic import View
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required

from wms.models import Dataset, Server, Variable, Style, UnidentifiedDataset
from wms.utils import get_layer_from_request
from wms.tasks import update_dataset, update_layers, update_time_cache, update_grid_cache
from wms import gfi_handler
from wms import wms_handler
from wms import logger


@cache_page(604800, cache="page")
def crossdomain(request):
    with open(os.path.join(settings.PROJECT_ROOT, "..", "wms", "static", "wms", "crossdomain.xml")) as f:
        response = HttpResponse(content_type="text/xml")
        response.write(f.read())
    return response


@cache_page(604800, cache="page")
def favicon(request):
    with open(os.path.join(settings.PROJECT_ROOT, "..", "wms", "static", "wms", "favicon.ico"), 'rb') as f:
        response = HttpResponse(content_type="image/x-icon")
        response.write(f.read())
    return response


def datasets(request):
    datasets = Dataset.objects.all()
    data = serializers.serialize('json', datasets)
    return HttpResponse(data, content_type='application/json')


def index(request):
    datasets = Dataset.objects.all()
    unidentified_datasets = UnidentifiedDataset.objects.all()
    context = { "datasets" : datasets, "unidentified_datasets" : unidentified_datasets }
    return TemplateResponse(request, 'wms/index.html', context)


def groups(request):
    return HttpResponse('ok')


def authenticate_view(request):
    if request.user.is_authenticated():
        return True

    if request.method == 'POST':
        uname = request.POST.get('username', None)
        passw = request.POST.get('password', None)
    elif request.method == 'GET':
        uname = request.GET.get('username', None)
        passw = request.GET.get('password', None)

    user = authenticate(username=uname, password=passw)

    if user is not None and user.is_active:
        login(request, user)
        return True
    else:
        return False


def logout_view(request):
    logout(request)


def normalize_get_params(request):
    gettemp = request.GET.copy()
    for key in request.GET.keys():
        gettemp[key.lower()] = request.GET[key]
    request.GET = gettemp
    return request


def demo(request):
    context = { 'datasets'  : Dataset.objects.all()}
    return render(request, 'wms/demo.html', context)


def enhance_getmap_request(dataset, layer, request):
    gettemp = request.GET.copy()

    # 'time' parameter
    times = wms_handler.get_times(request)
    dimensions = wms_handler.get_dimensions(request)
    defaults = layer.defaults

    newgets = dict(
        starting=times.min,
        ending=times.max,
        time=wms_handler.get_time(request),
        crs=wms_handler.get_projection(request),
        bbox=wms_handler.get_bbox(request),
        wgs84_bbox=wms_handler.get_wgs84_bbox(request),
        colormap=wms_handler.get_colormap(request, default=defaults.colormap),
        colorscalerange=wms_handler.get_colorscalerange(request, defaults.min, defaults.max),
        elevation=wms_handler.get_elevation(request),
        width=dimensions.width,
        height=dimensions.height,
        image_type=wms_handler.get_imagetype(request, default=defaults.image_type),
        logscale=wms_handler.get_logscale(request, defaults.logscale),
        vectorscale=wms_handler.get_vectorscale(request),
        vectorstep=wms_handler.get_vectorstep(request),
        numcontours=wms_handler.get_num_contours(request, default=defaults.numcontours)
    )
    gettemp.update(newgets)
    request.GET = gettemp

    # Check required parameters here and raise a ValueError if needed

    return request


def enhance_getlegendgraphic_request(dataset, layer, request):
    gettemp = request.GET.copy()

    dimensions = wms_handler.get_dimensions(request, default_width=110, default_height=264)
    defaults = layer.defaults

    default_min = defaults.min or 0
    default_max = defaults.max or 10

    newgets = dict(
        colorscalerange=wms_handler.get_colorscalerange(request, default_min, default_max),
        width=dimensions.width,
        height=dimensions.height,
        image_type=wms_handler.get_imagetype(request, parameter='style', default=defaults.image_type),
        colormap=wms_handler.get_colormap(request, parameter='style', default=defaults.colormap),
        format=wms_handler.get_format(request),
        showlabel=wms_handler.get_show_label(request),
        showvalues=wms_handler.get_show_values(request),
        units=wms_handler.get_units(request, layer.units),
        logscale=wms_handler.get_logscale(request, defaults.logscale),
        horizontal=wms_handler.get_horizontal(request),
        numcontours=wms_handler.get_num_contours(request, default=defaults.numcontours)
    )
    gettemp.update(newgets)
    request.GET = gettemp
    return request


def enhance_getfeatureinfo_request(dataset, layer, request):
    gettemp = request.GET.copy()
    # 'time' parameter
    times = wms_handler.get_times(request)
    xy = wms_handler.get_xy(request)
    dimensions = wms_handler.get_dimensions(request)
    bbox = wms_handler.get_bbox(request)
    crs = wms_handler.get_projection(request)
    targets = wms_handler.get_gfi_positions(xy, bbox, crs, dimensions)

    newgets = dict(
        starting=times.min,
        ending=times.max,
        latitude=targets.latitude,
        longitude=targets.longitude,
        elevation=wms_handler.get_elevation(request),
        crs=crs,
        info_format=wms_handler.get_info_format(request)
    )
    gettemp.update(newgets)
    request.GET = gettemp
    return request


def enhance_getmetadata_request(dataset, layer, request):
    gettemp = request.GET.copy()

    # 'time' parameter
    dimensions = wms_handler.get_dimensions(request)

    newgets = dict(
        time=wms_handler.get_time(request),
        crs=wms_handler.get_projection(request),
        bbox=wms_handler.get_bbox(request),
        wgs84_bbox=wms_handler.get_wgs84_bbox(request),
        elevation=wms_handler.get_elevation(request),
        width=dimensions.width,
        height=dimensions.height,
        item=wms_handler.get_item(request)
    )
    gettemp.update(newgets)
    request.GET = gettemp
    return request


class LogsView(View):

    @method_decorator(login_required)
    def get(self, request):
        if settings.LOGFILE is not None and os.path.isfile(settings.LOGFILE):
            with open(settings.LOGFILE) as f:
                lines = "\n".join([ x.strip() for x in f.readlines()[-400:] ])
        else:
            lines = "No logfile is setup in sci-wms!"

        return TemplateResponse(request, 'wms/logs.html', dict(lines=lines))


class DefaultsView(View):

    def get(self, request):
        defaults = Variable.objects.all()
        return TemplateResponse(request, 'wms/defaults.html', dict(defaults=defaults))


class DatasetShowView(View):

    def get(self, request, dataset):
        dataset = get_object_or_404(Dataset, slug=dataset)
        styles = { x.code: x.code for x in Style.objects.order_by('image_type') }
        styles = json.dumps(OrderedDict(sorted(styles.items(), key=lambda x: x[0])))
        return TemplateResponse(request, 'wms/dataset.html', dict(dataset=dataset, styles=styles))


class DatasetGridUpdateView(View):

    @method_decorator(login_required)
    def get(self, request, dataset):
        dataset = get_object_or_404(Dataset, slug=dataset)
        update_grid_cache(dataset.pk)
        return HttpResponse(json.dumps({ "message" : "Scheduled" }), content_type='application/json')


class DatasetTimeUpdateView(View):

    @method_decorator(login_required)
    def get(self, request, dataset):
        dataset = get_object_or_404(Dataset, slug=dataset)
        update_time_cache(dataset.pk)
        return HttpResponse(json.dumps({ "message" : "Scheduled" }), content_type='application/json')


class DatasetLayersUpdateView(View):

    @method_decorator(login_required)
    def get(self, request, dataset):
        dataset = get_object_or_404(Dataset, slug=dataset)
        update_layers(dataset.pk)
        return HttpResponse(json.dumps({ "message" : "Scheduled" }), content_type='application/json')


class DatasetUpdateView(View):

    @method_decorator(login_required)
    def get(self, request, dataset):
        dataset = get_object_or_404(Dataset, slug=dataset)
        update_dataset(dataset.pk)
        return HttpResponse(json.dumps({ "message" : "Scheduled" }), content_type='application/json')


class DatasetDeleteCacheView(View):

    @method_decorator(login_required)
    def get(self, request, dataset):
        dataset = get_object_or_404(Dataset, slug=dataset)
        dataset.clear_cache()
        return HttpResponse(json.dumps({ "message" : 'Cleared' }), content_type='application/json')


class WmsView(View):

    def get(self, request, dataset):
        dataset = Dataset.objects.filter(slug=dataset).first()
        request = normalize_get_params(request)

        # This calls the passed in 'request' method on a Dataset and returns the response
        try:
            reqtype = request.GET['request']
            if reqtype.lower() == 'getcapabilities':
                return TemplateResponse(request, 'wms/getcapabilities.xml', dict(gfi_formats=gfi_handler.FORMATS, dataset=dataset, server=Server.objects.first()), content_type='application/xml')
            else:
                layer = get_layer_from_request(dataset, request)
                if not layer:
                    raise ValueError('Could not find a layer named "{}"'.format(request.GET.get('layers')))
                if reqtype.lower() == 'getmap':
                    request = enhance_getmap_request(dataset, layer, request)
                elif reqtype.lower() == 'getlegendgraphic':
                    request = enhance_getlegendgraphic_request(dataset, layer, request)
                elif reqtype.lower() == 'getfeatureinfo':
                    request = enhance_getfeatureinfo_request(dataset, layer, request)
                elif reqtype.lower() == 'getmetadata':
                    request = enhance_getmetadata_request(dataset, layer, request)

                return getattr(dataset, reqtype.lower())(layer, request)

        except NotImplementedError:
            logger.exception('Returning a 500:')
            return HttpResponse('"{}" is not implemented for a {}'.format(reqtype, dataset.__class__.__name__), status=500, reason="Could not process inputs", content_type="application/json")
        except BaseException as e:
            logger.exception('Returning a 500:')
            return HttpResponse(str(e), status=500, reason="Could not process inputs", content_type="application/json")
