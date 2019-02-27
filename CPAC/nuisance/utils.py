import os
import re
import numpy as np
import nibabel as nb

import nipype.pipeline.engine as pe
import nipype.interfaces.utility as util
import nipype.interfaces.fsl as fsl
import nipype.interfaces.ants as ants
from nipype.interfaces import afni

from CPAC.utils.function import Function

import scipy.signal as signal


def find_offending_time_points(fd_file_path=None, dvars_file_path=None,
                               fd_threshold=None, dvars_threshold=None,
                               number_of_previous_trs_to_remove=0,
                               number_of_subsequent_trs_to_remove=0):
    """

    Applies criterion in method to find time points whose FD or DVARS (or both) are above threshold

    :param thresh_metric: metric for determining offending time points, either 'FD', 'DVARS', or 'FD+DVARS'. In the last
        case time points will be chosen from the intersection of the FD and DVARS criteria
    :param out_file_path: name of output TSV, which will contain the indices of offending time points list in a
        single column
    :param fd_file_path: path to TSV containing framewise displacement as a single column
    :param dvars_file_path: path to TSV containing DVARS as a single column
    :param fd_threshold: threshold to apply to framewise displacement, can be a value such as 0.2 or a floating
      point multiple of the standard deviation specified as, e.g. '1.5 SD'
    :param dvars_threshold: threshold to apply to DVARS, can be a value such as 0.5 or a floating
      point multiple of the standard deviation specified as, e.g. '1.5 SD'
    :param number_of_previous_trs_to_remove: extent of censorship window before the censor
    :param number_of_subsequent_trs_to_remove: extent of censorship window after the censor

    :return: file path to output file
    """
    import numpy as np
    import os
    import re

    offending_time_points = []
    time_course_len = 0

    if fd_file_path:

        if not os.path.isfile(fd_file_path):
            raise ValueError(
                "Framewise displacement file {0} could not be found."
                .format(fd_file_path)
            )

        if not fd_threshold:
            raise ValueError("Method FD requires the specification of a "
                             "framewise displacement threshold, none received")

        framewise_displacement = np.loadtxt(fd_file_path)

        time_course_len = framewise_displacement.shape[0]

        try:
            fd_threshold_sd = \
                re.match(r"([0-9]*\.*[0-9]*)\s*SD", str(fd_threshold))

            if fd_threshold_sd:
                fd_threshold_sd = float(fd_threshold_sd.groups()[0])
                fd_threshold = framewise_displacement.mean() + \
                    fd_threshold_sd * framewise_displacement.std()
            else:
                fd_threshold = float(fd_threshold)
        except:
            raise ValueError("Could not translate fd_threshold {0} into a "
                             "meaningful value".format(fd_threshold))

        offending_time_points = \
            np.where(framewise_displacement > fd_threshold)[0].tolist()

    if dvars_file_path:

        if not os.path.isfile(dvars_file_path):
            raise ValueError(
                "DVARS file {0} could not be found.".format(dvars_file_path))

        if not dvars_threshold:
            raise ValueError("Method DVARS requires the specification of a "
                             "DVARS threshold, none received")

        dvars = np.array([0.0] + np.loadtxt(dvars_file_path).tolist())

        time_course_len = dvars.shape[0]

        try:
            dvars_threshold_sd = \
                re.match(r"([0-9]*\.*[0-9]*)\s*SD", str(dvars_threshold))

            if dvars_threshold_sd:
                dvars_threshold_sd = float(dvars_threshold_sd.groups()[0])
                dvars_threshold = dvars.mean() + \
                    dvars_threshold_sd * dvars.std()
            else:
                dvars_threshold = float(dvars_threshold)
        except:
            raise ValueError("Could not translate dvars_threshold {0} into a "
                             "meaningful value".format(dvars_threshold))

        if not offending_time_points:
            offending_time_points = \
                np.where(dvars > dvars_threshold)[0].tolist()
        else:
            offending_time_points = list(set(offending_time_points).intersection(
                np.where(dvars > dvars_threshold)[0].tolist()))

    extended_censors = []
    for censor in offending_time_points:
        extended_censors += range(
            (censor - number_of_previous_trs_to_remove),
            (censor + number_of_subsequent_trs_to_remove + 1)
        )

    extended_censors = [
        censor
        for censor in np.unique(extended_censors)
        if 0 <= censor < time_course_len
    ]

    censor_vector = np.ones((time_course_len, 1))
    censor_vector[extended_censors] = 0

    out_file_path = os.path.join(os.getcwd(), "censors.tsv")
    np.savetxt(out_file_path, censor_vector, fmt='%d')

    return out_file_path


def create_temporal_variance_mask(functional_file_path, mask_file_path,
                                  threshold, by_slice=False):
    """
    Create a mask by applying threshold to the temporal variance of 4D nifti file in functional_file_path. Only
    non-zero voxels in mask will be considered for inclusion.

    :param functional_file_path: 4D nifti file containing functional data
    :param output_file_name: name of 3D nifti file containing created mask, the current directory will be prepended
        to this value, and the mask will be written to the resulting location.
    :param mask_file_path: name of 3D nifti file containing mask to use to restrict the voxels considered by the masking
        operation
    :param threshold: only voxels whose temporal variance meet the threshold criterion will be included in the created
        mask. Appropriate values are:
         - a floating point value, values whose temporal variance is greater than this value will be included in mask
         - a floating point value followed by SD, (1.5SD), values whose temporal variance is greater that 1.5 standard
              deviations of voxels will be included in the mask
         - a floating point value followed by PCT, (2PCT), values whose temporal variance is in the specified percentile
              _from the top_ will be included in the mask. For example 2pct results in the top 2% voxels being included
    :param by_slice: indicates whether threshold criterion should be applied by slice, or to all data, only changes
        result for thresholds expressed in terms of SD or pct
    :return: the full path of the 3D nifti file containing the mask created by this operation.
    """

    # begin by verifying the input parameters
    if not (functional_file_path and (
        functional_file_path.endswith(".nii") or
        functional_file_path.endswith(".nii.gz")
    )):
        raise ValueError("Improper functional file specified ({0}), "
                         "should be a 4D nifti file."
                         .format(functional_file_path))

    if not (mask_file_path and (
        mask_file_path.endswith(".nii") or
        mask_file_path.endswith(".nii.gz")
    )):
        raise ValueError("Improper mask file specified ({0}), "
                         "should be a 3D nifti file.".format(mask_file_path))

    if not threshold:
        raise ValueError("Threshold must be specified. Received None")

    threshold_method = "VAR"
    threshold_value = threshold

    if isinstance(threshold, str):
        regex_match = {
            "SD": r"([0-9]+(\.[0-9]+)?)\s*SD",
            "PCT": r"([0-9]+(\.[0-9]+)?)\s*PCT",
        }

        for method, regex in regex_match.items():
            matched = re.match(regex, threshold)
            if matched:
                threshold_method = method
                threshold_value = matched.groups()[0]

    try:
        threshold_value = float(threshold_value)
    except:
        raise ValueError("Error converting threshold value {0} from {1} to a "
                         "floating point number. The threshold value can "
                         "contain SD or PCT for selecting a threshold based on "
                         "the variance distribution, otherwise it should be a "
                         "floating point number.".format(threshold_value,
                                                         threshold))

    if threshold_value < 0:
        raise ValueError("Threshold value should be positive, instead of {0}."
                         .format(threshold_value))

    if threshold_method is "PCT" and threshold_value >= 100.0:
        raise ValueError("Percentile should be less than 100, received {0}."
                         .format(threshold_value))

    if not isinstance(by_slice, bool):
        raise ValueError("Parameter by_slice should be a boolean.")

    functional_data_img = nb.load(functional_file_path)

    if len(functional_data_img.shape) != 4 or functional_data_img.shape[3] < 3:
        raise ValueError("Functional data used to create mask ({0}) should be "
                         "4D and should contain 3 or more time points."
                         .format(functional_file_path))

    functional_data_variance = functional_data_img.get_data().var(axis=3)

    if mask_file_path:
        mask_image = nb.load(mask_file_path)

        if not(np.all(mask_image.shape == functional_data_img.shape[0:3]) and
               np.all(mask_image.affine == functional_data_img.affine)):

            raise ValueError("Shape and affine of mask image {0} ({1} {2}) "
                             "should match those of the functional data "
                             "{3} ({4} {5})".format(mask_file_path,
                                                    mask_image.shape,
                                                    mask_image.affine,
                                                    functional_file_path,
                                                    functional_data_img.shape,
                                                    functional_data_img.affine))

        mask_data = mask_image.get_data().astype(bool)
    else:
        mask_data = functional_data_variance > 0

    if by_slice is True:
        functional_data_variance_shape = (
            np.prod(functional_data_variance.shape[0:2]),
            functional_data_variance.shape[2]
        )
    else:
        functional_data_variance_shape = (
            np.prod(functional_data_variance.shape[0:3]),
            1,
        )

    functional_data_variance = \
        functional_data_variance.reshape(functional_data_variance_shape)

    # Conform output file and mask to functional data shape
    output_variance_mask = np.zeros(functional_data_variance.shape, dtype=bool)
    mask_data = mask_data.reshape(functional_data_variance.shape)

    for slice_number in range(functional_data_variance.shape[1]):

        # Make sure that there are some voxels at this slice
        if not np.any(mask_data[:, slice_number]):
            continue

        functional_data_variance_slice = \
            functional_data_variance[
                mask_data[:, slice_number],
                slice_number
            ]

        if threshold_method is "PCT":
            slice_threshold_value = np.percentile(
                functional_data_variance_slice,
                100.0 - threshold_value
            )

        elif threshold_method is "SD":
            slice_threshold_value = \
                functional_data_variance_slice.mean() + \
                threshold_value * functional_data_variance_slice.std()

        else:
            slice_threshold_value = threshold_value

        output_variance_mask[:, slice_number] = \
            mask_data[:, slice_number] & \
            (functional_data_variance[:, slice_number] > slice_threshold_value)

    # Make sure that the output mask is the correct shape and format
    output_variance_mask = np.uint8(output_variance_mask) \
                             .reshape(mask_image.shape)

    output_file_path = os.path.join(os.getcwd(), 'variance_mask.nii.gz')
    output_img = nb.Nifti1Image(output_variance_mask, mask_image.affine)
    output_img.to_filename(output_file_path)

    return output_file_path


def generate_summarize_tissue_mask(nuisance_wf,
                                   pipeline_resource_pool,
                                   regressor_descriptor,
                                   regressor_selector,
                                   use_ants=True):
    """
    Add tissue mask generation into pipeline.
    """

    steps = [
        key
        for key in ['tissue', 'resolution', 'erosion']
        if key in regressor_descriptor
    ]

    full_mask_key = "_".join(
        regressor_descriptor[s]
        for s in steps
    )

    for step_i, step in enumerate(steps):

        mask_key = "_".join(
            regressor_descriptor[s]
            for s in steps[:step_i+1]
        )

        if mask_key in pipeline_resource_pool:
            continue


        node_mask_key = re.sub(r"[^\w]", "_", mask_key)

        prev_mask_key = "_".join(
            regressor_descriptor[s]
            for s in steps[:step_i]
        )


        if step is 'tissue':

            if mask_key.startswith('FunctionalVariance'):

                create_variance_mask_node = pe.Node(
                    Function(
                        input_names=[
                            'functional_file_path',
                            'mask_file_path',
                            'threshold',
                            'by_slice'
                        ],
                        output_names=['mask_file_path'],
                        function=create_temporal_variance_mask,
                        as_module=True,
                    ),
                    name='create_temporal_variance_mask_{}'
                         .format(node_mask_key)
                )

                nuisance_wf.connect(*(
                    pipeline_resource_pool['Functional'] +
                    (create_variance_mask_node, 'functional_file_path')
                ))

                nuisance_wf.connect(*(
                    pipeline_resource_pool['GlobalSignal'] +
                    (create_variance_mask_node, 'mask_file_path')
                ))

                create_variance_mask_node.inputs.threshold = \
                    regressor_selector['threshold']

                create_variance_mask_node.inputs.by_slice = \
                    regressor_selector['by_slice']

                pipeline_resource_pool[mask_key] = \
                    (create_variance_mask_node, 'mask_file_path')

            elif mask_key == 'CerebrospinalFluid':

                transforms = pipeline_resource_pool['Transformations']

                # reduce CSF mask to the lateral ventricles
                mask_cfs_with_lat_ven = pe.Node(interface=afni.Calc(), name='mask_cfs_with_lat_ven')
                mask_cfs_with_lat_ven.inputs.expr = 'step(a)*step(b)'
                mask_cfs_with_lat_ven.inputs.outputtype = 'NIFTI_GZ'
                mask_cfs_with_lat_ven.inputs.out_file = 'cfs_lat_ven_mask.nii.gz'

                if use_ants is True:

                    # perform the transform using ANTS
                    collect_linear_transforms = pe.Node(util.Merge(3), name='ho_mni_to_2mm_ants_collect_linear_transforms')

                    nuisance_wf.connect(*(transforms['anat_to_mni_initial_xfm'] + (collect_linear_transforms, 'in1')))
                    nuisance_wf.connect(*(transforms['anat_to_mni_rigid_xfm'] + (collect_linear_transforms, 'in2')))
                    nuisance_wf.connect(*(transforms['anat_to_mni_affine_xfm'] + (collect_linear_transforms, 'in3')))

                    lat_ven_mni_to_anat = pe.Node(interface=ants.ApplyTransforms(), name='lat_ven_mni_to_anat_ants')
                    lat_ven_mni_to_anat.inputs.invert_transform_flags = [True, True, True]
                    lat_ven_mni_to_anat.inputs.interpolation = 'NearestNeighbor'
                    lat_ven_mni_to_anat.inputs.dimension = 3

                    nuisance_wf.connect(collect_linear_transforms, 'out', lat_ven_mni_to_anat, 'transforms')

                    nuisance_wf.connect(*(pipeline_resource_pool['Ventricles'] + (lat_ven_mni_to_anat, 'input_image')))
                    nuisance_wf.connect(*(pipeline_resource_pool['CerebrospinalFluidUnmasked'] + (lat_ven_mni_to_anat, 'reference_image')))

                    nuisance_wf.connect(lat_ven_mni_to_anat, 'output_image', mask_cfs_with_lat_ven, 'in_file_b')

                else:

                    # perform the transform using FLIRT
                    lat_ven_mni_to_anat = pe.Node(interface=fsl.FLIRT(), name='lat_ven_mni_to_anat_flirt')
                    lat_ven_mni_to_anat.inputs.interp = 'nearestneighbour'

                    nuisance_wf.connect(*(transforms['mni_to_anat_linear_xfm'] + (lat_ven_mni_to_anat, 'in_matrix_file')))
                    nuisance_wf.connect(*(pipeline_resource_pool['Ventricles'] + (lat_ven_mni_to_anat, 'in_file')))
                    nuisance_wf.connect(*(pipeline_resource_pool['CerebrospinalFluidUnmasked'] + (lat_ven_mni_to_anat, 'reference')))

                    nuisance_wf.connect(lat_ven_mni_to_anat, 'out_file', mask_cfs_with_lat_ven, 'in_file_b')

                nuisance_wf.connect(*(pipeline_resource_pool['CerebrospinalFluidUnmasked'] + (mask_cfs_with_lat_ven, 'in_file_a')))

                pipeline_resource_pool[mask_key] = \
                    (mask_cfs_with_lat_ven, 'out_file')

        if step is 'resolution':

            mask_to_epi = pe.Node(interface=fsl.FLIRT(),
                                  name='mask_to_epi_flirt_applyxfm_{}'
                                       .format(node_mask_key))

            if regressor_selector['extraction_resolution'] == "Functional":
                nuisance_wf.connect(*(
                    pipeline_resource_pool['Functional'] +
                    (mask_to_epi, 'reference')
                ))
            else:

                resolution = regressor_selector['extraction_resolution']
                mask_to_epi.inputs.apply_isoxfm = \
                    resolution

                nuisance_wf.connect(*(
                    pipeline_resource_pool['Anatomical_{}mm'
                                           .format(resolution)] +
                    (mask_to_epi, 'reference')
                ))

            nuisance_wf.connect(*(
                pipeline_resource_pool[prev_mask_key] +
                (mask_to_epi, 'in_file')
            ))

            pipeline_resource_pool[mask_key] = \
                (mask_to_epi, 'out_file')


        if step is 'erosion':

            erode_mask_node = pe.Node(interface=afni.Calc(),
                                      name='erode_mask_node_{}'
                                           .format(node_mask_key))
            erode_mask_node.inputs.args = "-b a+i -c a-i -d a+j " + \
                                          "-e a-j -f a+k -g a-k"
            erode_mask_node.inputs.expr = 'a*(1-amongst(0,b,c,d,e,f,g))'
            erode_mask_node.inputs.outputtype = 'NIFTI_GZ'
            erode_mask_node.inputs.out_file = 'erode_mask_node.nii.gz'

            nuisance_wf.connect(*(
                pipeline_resource_pool[prev_mask_key] +
                (erode_mask_node, 'in_file_a')
            ))

            pipeline_resource_pool[mask_key] = \
                (erode_mask_node, 'out_file')


    return pipeline_resource_pool, full_mask_key


def summarize_timeseries(functional_path, masks_path, summary):

    if type(summary) is not dict:
        summary = {'method': summary}

    masks_img = [nb.load(mask_path) for mask_path in masks_path]
    mask = np.sum(np.array([
        mask_img.get_data() for mask_img in masks_img
    ]), axis=0) > 0.0

    functional_img = nb.load(functional_path)
    masked_functional = functional_img.get_data()[mask]

    regressors = np.zeros(masked_functional.shape[-1])

    if summary['method'] == 'Mean':
        regressors = masked_functional.mean(0)

    if summary['method'] == 'NormMean':
        masked_functional /= np.linalg.norm(masked_functional, 2)
        regressors = masked_functional.mean(0)

    if summary['method'] == 'DetrendNormMean':
        masked_functional = \
            signal.detrend(masked_functional, axis=1, type='linear').T

        masked_functional /= np.linalg.norm(masked_functional, 2)
        regressors = masked_functional.mean(0)

    if summary['method'] == 'PC':
        mean_signal = np.tile(
            masked_functional.mean(1),
            (masked_functional.shape[1], 1)
        )
        U, _, _ = np.linalg.svd(
            masked_functional.T - mean_signal,
            full_matrices=False
        )
        regressors = U[:, 0:summary['components']]

    output_file_path = os.path.join(os.getcwd(), 'summary_regressors.1D')
    np.savetxt(output_file_path, regressors, fmt='%.18f')

    return output_file_path


class NuisanceRegressor(object):

    def __init__(self, selector, selectors):
        self.selector = selector
        self.selectors = selectors

    def get(self, key, default=None):
        return self.selector.get(key, default)

    def __contains__(self, key):
        return key in self.selector

    def __getitem__(self, key):
        return self.selector[key]

    def _derivative_params(self, selector):
        nr_repr = ''
        if not selector:
            return nr_repr
        if selector.get('include_squared'):
            nr_repr += 'S'
        if selector.get('include_delayed'):
            nr_repr += 'D'
        if selector.get('include_delayed_squared'):
            nr_repr += 'B'
        return nr_repr

    def _summary_params(self, selector):
        summ = selector['summary']

        methods = {
            'PC': 'PC',
            'Mean': 'M',
            'NormMean': 'NM',
            'DetrendMean': 'DM',
            'DetrendNormMean': 'DNM',
        }

        if type(summ) == dict:
            method = summ['method']
            rep = methods[method]
            if method == 'PC':
                rep += "%d" % summ['components']
        else:
            rep = methods[summ]

        return rep

    def __repr__(self):
        regs = {
            'GreyMatter': 'GM',
            'WhiteMatter': 'WM',
            'CerebrospinalFluid': 'CSF',
            'tCompCor': 'tC',
            'aCompCor': 'aC',
            'GlobalSignal': 'G',
            'Motion': 'M',
            'PolyOrt': 'P',
            'Bandpass': 'B',
            'Censor': 'C',
        }

        tissues = ['GreyMatter', 'WhiteMatter', 'CerebrospinalFluid']

        selectors_representations = []

        # tC-1.5PT-PC5S-SDB
        # aC-WC-2mmE-PC5-SDB

        # WM-2mmE-PC5-SDB
        # CSF-2mmE-M-SDB
        # GM-2mmE-DNM-SDB

        # G-PC5-SDB
        # M-SDB
        # C-S-FD1.5SD-D1.5SD
        # PR-2
        # BP-T0.01-B0.1

        for r in regs.keys():
            if r not in self.selector:
                continue

            s = self.selector[r]

            pieces = [regs[r]]

            if r in tissues:
                if s.get('extraction_resolution'):
                    res = "%.2f" % s['extraction_resolution']
                    if s.get('erode_mask'):
                        res += 'E'

                pieces += [self._summary_params(s)]
                pieces += [self._derivative_params(s)]

            elif r == 'tCompCor':

                threshold = ""
                if s.get('by_slice'):
                    threshold += 'S'
                t = s.get('threshold')
                if t:
                    if type(t) != str:
                        t = "%.2f" % t
                    threshold += t

                pieces += [threshold]
                pieces += [self._summary_params(s)]
                pieces += [self._derivative_params(s)]

            elif r == 'aCompCor':
                if s.get('tissues'):
                    pieces += ["+".join([regs[t] for t in s['tissues']])]
                if s.get('extraction_resolution'):
                    res = "%.2f" % s['extraction_resolution']
                    if s.get('erode_mask'):
                        res += 'E'

                pieces += [self._summary_params(s)]
                pieces += [self._derivative_params(s)]

            elif r == 'Global':
                pieces += [self._summary_params(s)]
                pieces += [self._derivative_params(s)]

            elif r == 'Motion':
                pieces += [self._derivative_params(s)]

            elif r == 'PolyOrt':
                pieces += ['%d' % s['degree']]

            elif r == 'BandPass':
                pieces += ['T%.2f' % s['top_frequency']]
                pieces += ['B%.2f' % s['bottom_frequency']]

            elif r == 'Censor':
                censoring = {
                    'Kill': 'K',
                    'Zero': 'Z',
                    'Interpolate': 'I',
                    'SpikeRegression': 'S',
                }

                thresholds = {
                    'FD': 'FD',
                    'DVARS': 'DV',
                }

                pieces += [censoring[s['method']]]

                trs_range = ['0', '0']
                if s.get('number_of_previous_trs_to_remove'):
                    trs_range[0] = '%d' % s['number_of_previous_trs_to_remove']
                if s.get('number_of_subsequent_trs_to_remove'):
                    trs_range[1] = '%d' % s['number_of_subsequent_trs_to_remove']

                pieces += ['+'.join(trs_range)]

                threshs = sorted(s['thresholds'], reverse=True, key=lambda d: d['type'])
                for st in threshs:
                    thresh = thresholds[st['type']]
                    if type(st['value']) == str:
                        thresh += st['value']
                    else:
                        thresh += "%.2g" % st['value']

                    pieces += [thresh]

            selectors_representations += ['-'.join(filter(None, pieces))]

        return "_".join(selectors_representations)
