#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Functions for creating connectome connectivity matrices."""
import os
import re
import numpy as np
from nilearn.connectome import ConnectivityMeasure
from nilearn.input_data import NiftiLabelsMasker
from nipype import logging
from nipype.interfaces import utility as util
from CPAC.pipeline import nipype_pipeline_engine as pe
from CPAC.pipeline.schema import valid_options
from CPAC.utils.datasource import create_roi_mask_dataflow
from CPAC.utils.interfaces.function import Function
from CPAC.utils.interfaces.netcorr import NetCorr

logger = logging.getLogger('nipype.workflow')
tse_analyses = {'Avg': 'Mean'}
methods = {
    'AFNI': {'Pearson': '', 'Partial': '-part_corr'},
    'Nilearn': {'Pearson': 'correlation', 'Partial': 'partial correlation'}
}
tools = {'afni': 'AFNI', 'nilearn': 'Nilearn'}


def _connectome_name(time_series, method):
    """Helper function to create connectome file filename

    Parameters
    ----------
    time_series : str
        path to input time series

    method : str
        BIDS entity value for `desc-` key

    Returns
    -------
    str
    """
    method = method.replace(' ', '+')
    return os.path.abspath(os.path.join(
        os.path.dirname(time_series),
        time_series.replace(
            '_timeseries.1D',
            f'_desc-{method}_connectome.npy'
        )
    ))


def _get_method(method, tool):
    """Helper function to get tool's method string

    Parameters
    ----------
    method : str

    tool : str

    Returns
    -------
    str or NotImplemented
    """
    tool = tools[tool.lower()]  # make case-insensitive
    cm_method = methods[tool].get(method, NotImplemented)
    if cm_method is NotImplemented:
        logger.warning(NotImplementedError(
            f'{method} has not yet been implemented for {tool} in C-PAC.'
        ))
    return cm_method


def compute_correlation(time_series, method):
    """Function to create a numpy array file [1] containing a
    correlation matrix for a given time series and method.

    Parameters
    ----------
    time_series : str
        path to time series output

    method : str
        correlation matrix method. See https://fcp-indi.github.io/docs/nightly/user/tse#configuring-roi-time-series-extraction
        for options and how to configure.

    References
    ----------
    .. [1] The NumPy community (2021). NPY format. https://numpy.org/doc/stable/reference/generated/numpy.lib.format.html#npy-format
    """  # pylint: disable=line-too-long  # noqa E501
    desc_regex = re.compile(r'\_desc.*(?=\_)')

    data = np.genfromtxt(time_series).T

    existing_desc = desc_regex.search(time_series)
    if hasattr(existing_desc, 'group'):
        matrix_file = time_series.replace(
            existing_desc.group(),
            '+'.join([
                existing_desc.group(),
                method
            ])
        ).replace('_timeseries.1D', '_connectome.npy')
    else:
        matrix_file = _connectome_name(time_series, method)

    method = _get_method(method, 'Nilearn')
    if method is NotImplemented:
        return NotImplemented

    connectivity_measure = ConnectivityMeasure(kind=method)
    connectome = connectivity_measure.fit_transform([data])[0]

    np.save(matrix_file, connectome)
    return matrix_file


def compute_connectome_nilearn(parcellation, timeseries, method):
    """Function to compute a connectome matrix using Nilearn

    Parameters
    ----------
    parcelation : Niimg-like object
        http://nilearn.github.io/manipulating_images/input_output.html#niimg-like-objects
        Region definitions, as one image of labels.

    timeseries : str
        path to timeseries image

    method: str
        'Pearson' or 'Partial'

    Returns
    -------
    numpy.ndarray or NotImplemented
    """
    output = _connectome_name(timeseries, f'Nilearn{method}')
    method = _get_method(method, 'Nilearn')
    if method is NotImplemented:
        return NotImplemented
    masker = NiftiLabelsMasker(labels_img=parcellation,
                               standardize=True,
                               verbose=True)
    timeser = masker.fit_transform(timeseries)
    correlation_measure = ConnectivityMeasure(kind=method)
    corr_matrix = correlation_measure.fit_transform([timeser])[0]
    np.fill_diagonal(corr_matrix, 0)
    np.savetxt(output, corr_matrix)
    return corr_matrix


def create_connectome(name='connectome'):

    wf = pe.Workflow(name=name)

    inputspec = pe.Node(
        util.IdentityInterface(fields=[
            'timeseries',
            'measure'
        ]),
        name='inputspec'
    )

    outputspec = pe.Node(
        util.IdentityInterface(fields=[
            'connectome',
        ]),
        name='outputspec'
    )

    node = pe.Node(Function(input_names=['timeseries', 'measure'],
                            output_names=['connectome'],
                            function=compute_correlation,
                            as_module=True),
                   name='connectome')

    wf.connect([
        (inputspec, node, [('timeseries', 'timeseries')]),
        (inputspec, node, [('measure', 'measure')]),
        (node, outputspec, [('connectome', 'connectome')]),
    ])

    return wf


def create_connectome_nilearn(name='connectomeNilearn'):
    wf = pe.Workflow(name=name)
    inputspec = pe.Node(
        util.IdentityInterface(fields=[
            'parcellation',
            'timeseries',
            'measure'
        ]),
        name='inputspec'
    )
    outputspec = pe.Node(
        util.IdentityInterface(fields=[
            'connectome',
        ]),
        name='outputspec'
    )
    node = pe.Node(Function(input_names=['parcellation', 'timeseries',
                                         'measure'],
                            output_names=['connectome'],
                            function=compute_connectome_nilearn,
                            as_module=True),
                   name='connectome')
    wf.connect([
        (inputspec, node, [('parcellation', 'parcellation')]),
        (inputspec, node, [('timeseries', 'timeseries')]),
        (inputspec, node, [('measure', 'measure')]),
        (node, outputspec, [('connectome', 'connectome')]),
    ])
    return wf


def timeseries_connectivity_matrix(wf, cfg, strat_pool, pipe_num, opt=None):
    '''
    {"name": "timeseries_connectivity_matrix",
     "config": ["connectivity_matrix"],
     "switch": "None",
     "option_key": "using",
     "option_val": ["AFNI", "Nilearn"],
     "inputs": ["timeseries"],
     "outputs": ["connectome"]}
    '''  # pylint: disable=invalid-name,unused-argument
    outputs = {}
    for timeseries_analysis in cfg['timeseries_extraction', 'tse_roi_paths']:
        atlas = timeseries_analysis.split('/')[
            -1].split('.')[0].replace('_', '')
        analysis = tse_analyses.get(
            cfg['timeseries_extraction', 'tse_roi_paths', timeseries_analysis]
        )
        if analysis is None:
            continue
        node, out = strat_pool.get_data(f'atlas-{atlas}_desc-{analysis}_'
                                        'timeseries')
        for measure in cfg['connectivity_matrix', 'measure']:
            if measure in valid_options['connectivity_matrix']['measure']:
                if opt in ['AFNI', 'Nilearn']:
                    implementation = _get_method(measure, opt)
                    if implementation is NotImplemented:
                        continue
                    roi_dataflow = create_roi_mask_dataflow(
                            cfg.timeseries_extraction['tse_atlases']['Avg'],
                            f'roi_dataflow_{pipe_num}')
                    roi_dataflow.inputs.inputspec.set(
                        creds_path=cfg.pipeline_setup['input_creds_path'],
                        dl_dir=cfg.pipeline_setup['working_directory']['path']
                    )

                    if opt == 'Nilearn':
                        timeseries_correlation = pe.Node(Function(
                            input_names=['parcellation', 'timeseries'],
                            output_names=['connectomeNilearn'],
                            function=create_connectome_nilearn,
                            as_module=True
                        ), name=f'connectomeNilearn{measure}_{pipe_num}')
                        timeseries_correlation.inputs.measure = measure

                    elif opt == "AFNI":
                        timeseries_correlation = pe.Node(
                            NetCorr(),
                            name=f'connectomeAFNI{measure}_{pipe_num}')
                        if implementation:
                            timeseries_correlation.inputs.part_corr = (
                                measure == 'Partial'
                            )

                    wf.connect(roi_dataflow, 'outputspec.out_file',
                               timeseries_correlation, 'parcellation')

                else:
                    timeseries_correlation = pe.Node(Function(
                        input_names=['timeseries', 'measure'],
                        output_names=['connectome'],
                        function=create_connectome,
                        as_module=True
                    ), name=f'connectome{measure}_{pipe_num}')

            wf.connect(node, out,
                       timeseries_correlation, 'timeseries')

    return (wf, outputs)
