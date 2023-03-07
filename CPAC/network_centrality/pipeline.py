from CPAC.pipeline import nipype_pipeline_engine as pe
import nipype.interfaces.fsl as fsl
import nipype.interfaces.utility as util

from nipype import logging

from CPAC.utils.interfaces.function import Function
from CPAC.network_centrality.network_centrality import create_centrality_wf
from CPAC.network_centrality.utils import merge_lists, check_centrality_params
from CPAC.pipeline.schema import valid_options

logger = logging.getLogger('nipype.workflow')


def connect_centrality_workflow(workflow, c, resample_functional_to_template,
                                template_node, template_out, merge_node,
                                method_option, pipe_num):
    template = c.network_centrality['template_specification_file']

    # Set method_options variables
    if method_option == 'degree_centrality':
        out_list = 'deg_list'
    elif method_option == 'eigenvector_centrality':
        out_list = 'eig_list'
    elif method_option == 'local_functional_connectivity_density':
        out_list = 'lfcd_list'

    threshold_option = c.network_centrality[method_option][
        'correlation_threshold_option'
    ]
    threshold = c.network_centrality[method_option]['correlation_threshold']

    # Init workflow name and resource limits
    wf_name = f'afni_centrality_{method_option}_{pipe_num}'
    num_threads = c.pipeline_setup['system_config'][
        'max_cores_per_participant'
    ]
    memory = c.network_centrality['memory_allocation']

    # Format method and threshold options properly and check for
    # errors
    method_option, threshold_option = check_centrality_params(method_option,
                                                              threshold_option,
                                                              threshold)

    # Change sparsity thresholding to % to work with afni
    if threshold_option == 'sparsity':
        threshold = threshold * 100

    afni_centrality_wf = \
        create_centrality_wf(wf_name, method_option,
                             c.network_centrality[method_option][
                                 'weight_options'], threshold_option,
                             threshold, num_threads, memory)

    workflow.connect(resample_functional_to_template, 'out_file',
                     afni_centrality_wf, 'inputspec.in_file')

    workflow.connect(template_node, template_out,
                     afni_centrality_wf, 'inputspec.template')

    if 'degree' in method_option:
        out_list = 'deg_list'
    elif 'eigen' in method_option:
        out_list = 'eig_list'
    elif 'lfcd' in method_option:
        out_list = 'lfcd_list'

    workflow.connect(afni_centrality_wf, 'outputspec.outfile_list',
                     merge_node, out_list)


@nodeblock(
    name="network_centrality",
    config=["network_centrality"],
    switch=["run"],
    inputs=[
        ("space-template_desc-preproc_bold", "T1w-brain-template-funcreg"),
        "template-specification-file",
    ],
    outputs={
        "space-template_dcw": {"Template": "T1w-brain-template-funcreg"},
        "space-template_dcb": {"Template": "T1w-brain-template-funcreg"},
        "space-template_ecw": {"Template": "T1w-brain-template-funcreg"},
        "space-template_ecb": {"Template": "T1w-brain-template-funcreg"},
        "space-template_lfcdw": {"Template": "T1w-brain-template-funcreg"},
        "space-template_lfcdb": {"Template": "T1w-brain-template-funcreg"},
    },
)
def network_centrality(wf, cfg, strat_pool, pipe_num, opt=None):
    '''Run Network Centrality.
    '''

    # Resample the functional mni to the centrality mask resolution
    resample_functional_to_template = pe.Node(
        interface=fsl.FLIRT(),
        name=f'resample_functional_to_template_{pipe_num}',
        mem_gb=4.0)

    resample_functional_to_template.inputs.set(
        interp='trilinear',
        in_matrix_file=cfg.registration_workflows['functional_registration'][
            'func_registration_to_template']['FNIRT_pipelines'][
            'identity_matrix'],
        apply_xfm=True
    )

    node, out = strat_pool.get_data("space-template_desc-preproc_bold")
    wf.connect(node, out, resample_functional_to_template, 'in_file')

    node, out = strat_pool.get_data("template-specification-file")
    wf.connect(node, out, resample_functional_to_template, 'reference')

    merge_node = pe.Node(Function(input_names=['deg_list',
                                               'eig_list',
                                               'lfcd_list'],
                                  output_names=['degree_weighted',
                                                'degree_binarized',
                                                'eigen_weighted',
                                                'eigen_binarized',
                                                'lfcd_weighted',
                                                'lfcd_binarized'],
                                  function=merge_lists,
                                  as_module=True),
                         name=f'centrality_merge_node_{pipe_num}')

    [connect_centrality_workflow(wf, cfg, resample_functional_to_template,
                                 node, out, merge_node,
                                 option, pipe_num) for option in
     valid_options['centrality']['method_options'] if
     cfg.network_centrality[option]['weight_options']]

    outputs = {}

    for option in valid_options['centrality']['method_options']:
        if cfg.network_centrality[option]['weight_options']:
            for weight in cfg.network_centrality[option]['weight_options']:
                _option = option.lower()
                _weight = weight.lower()
                if 'degree' in _option:
                    if 'weight' in _weight:
                        outputs['space-template_dcw'] = (merge_node,
                                                         'degree_weighted')
                    elif 'binarize' in _weight:
                        outputs['space-template_dcb'] = (merge_node,
                                                         'degree_binarized')
                elif 'eigen' in _option:
                    if 'weight' in _weight:
                        outputs['space-template_ecw'] = (merge_node,
                                                         'eigen_weighted')
                    elif 'binarize' in _weight:
                        outputs['space-template_ecb'] = (merge_node,
                                                         'eigen_binarized')
                elif 'lfcd' in _option or 'local_functional' in _option:
                    if 'weight' in _weight:
                        outputs['space-template_lfcdw'] = (merge_node,
                                                           'lfcd_weighted')
                    elif 'binarize' in _weight:
                        outputs['space-template_lfcdb'] = (merge_node,
                                                           'lfcd_binarized')

    return (wf, outputs)
