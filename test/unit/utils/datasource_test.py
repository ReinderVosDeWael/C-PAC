# test/unit/utils/datasource_test.py
#
#

'''
This module performs unit testing on the functions and classes from
the CPAC/utils/datasource.py module
'''

# Import packages
import unittest

# Tets case for cpac datasink
class DataSinkTestCase(unittest.TestCase):
    '''
    This class is a test case for the DataSink class implemented in
    CPAC that inherits from nipype's DataSink class

    Inherits
    --------
    unittest.TestCase class

    Attributes (class):
    ------------------
    see unittest.TestCase documentation

    Attributes (instance):
    '''

    # setUp method - init the input file
    def setUp(self):
        '''
        Method to instantiate input arguments for the
        AWS.fetch_creds() method via instance attributes

        Parameters
        ----------
        self : FetchCredsTestCase
            a unittest.TestCase-inherited class

        Returns
        -------
        None
            this function does not return any values, but populates the
            instance attributes for:

            self.base_dir : string
                filepath to base directory of DataSink
            self.creds_path : string
                filepath to AWS keys credentials file
            self.data_sink : nipype DataSink object
                object from nipype.interfaces.io.DataSink()
            self.ds_node : nipype Node object
                object from nipype.pipeline.engine.Node()
            self.in_file : string
                filepath to nifti file to use as test input to datasink
        '''

        # Import packages
        import os
        import sys

        import nipype.pipeline.engine as pe
        from CPAC.utils import datasource, test_init

        # Init variables
        try:
            input_dir = test_init.return_resource_subfolder('input')
            subj_id = test_init.return_test_subj()
            creds_path = test_init.return_aws_creds()
        except Exception as exc:
            print 'Unable to locate testing resources.\nError: %s' % exc
            sys.exit()

        # Datasink parameters
        base_dir = '/tmp/'

        # Get the input file as an anatomical scan from the CPAC_RESOURCES
        in_file = os.path.join(input_dir, 'site_1', subj_id, 'session_1',
                               'anat_1', 'mprage.nii.gz')

        # Init the datasinks
        data_sink = datasource.DataSink()
        ds_node = pe.Node(datasource.DataSink(), name='sinker_0')

        # Add instance variables to TestCase
        self.base_dir = base_dir
        self.creds_path = creds_path
        self.data_sink = data_sink
        self.ds_node = ds_node
        self.in_file = in_file

    # Check to see if datasink output was produced
    def check_output_exists(self, container, attr_folder):
        '''
        Method to check for the existence of a datasink output

        Parameters
        ----------
        self : unittest.TestCase
            instance method inherits self automatically; instance
            variables are used in the method
        container : string
            the datasink container sub-folder of its base directory
        attr_folder : string
            the datasink attribute, which generates a sub-folder of the
            container to store the output file value assigned

        Returns
        -------
        ds_out_exists : boolean
            flag indicating whether the expected output file exists
            from the datasink or not
        data_sink_output : string
            filepath of expected output file from data sink
        '''

        # Import packages
        import os

        # Init variables
        data_sink_outpath = os.path.join(self.base_dir, container,
                                         attr_folder,
                                         os.path.basename(self.in_file))

        # Check existence
        ds_out_exists = os.path.exists(data_sink_outpath)

        # Remove if it exists to free disk space
        if ds_out_exists:
            os.remove(data_sink_outpath)

        # Return if it exists or not as boolean and output path
        return ds_out_exists, data_sink_outpath

    # Check to see if datasink output was produced
    def check_output_exists_s3(self, data_sink):
        '''
        Method to check for the existence of a datasink output

        Parameters
        ----------
        self : unittest.TestCase
            instance method inherits self automatically; instance
            variables are used in the method

        Returns
        -------
        ds_out_exists : boolean
            flag indicating whether the expected output file exists
            from the datasink or not
        data_sink_output : string
            filepath of expected output file from data sink
        '''

        # Import packages
        import os
        import hashlib

        # Init variables
        src_s3_dict = {}
        s3_prefix = os.path.join(data_sink.inputs.base_directory,
                                 data_sink.inputs.container)
        # Isolate 's3://fcp-indi/' to strip out later
        s3_strip = '/'.join(s3_prefix.split('/')[:3])

        # Iterate over defined attribute keys and input sources
        for attr_key, src_f in data_sink.inputs._outputs.items():
            # If src is directory
            if os.path.isdir(src_f):
                src_files = []
                # Build a list of files
                for root, dirs, files in os.walk(src_f):
                    src_files.extend([os.path.join(root, fil) for fil in files])
                s3_root = os.path.join(s3_prefix, attr_key)
                # Build a list of corresponding s3 files
                s3_files = [fil.replace(src_f, s3_root) for fil in src_files]
                # Populate src -> s3 dictionary
                for idx, fil in enumerate(src_files):
                    s3_file = s3_files[idx]
                    src_s3_dict[fil] = s3_file
            # Else - src is a file
            else:
                # Map each source with s3 directory
                s3_file = os.path.join(s3_prefix, attr_key,
                                       os.path.basename(src_f))
                src_s3_dict[src_f] = os.path.join(s3_file)

        # Iterate over src -> s3 dictionary mapping and compare
        for src_f, s3_f in src_s3_dict.items():
            src_read = open(src_f, 'r').read()
            s3_key_path = s3_f.replace(s3_strip, '')
            dst_read = data_sink.bucket.get_key(s3_key_path)
            src_md5 = hashlib.md5(src_read).hexdigest()

            # If key doesn't exist, break with False and err message
            if not dst_read:
                dst_out_exists = False
                err_msg = '%s is not on S3' % s3_f
                break
            dst_md5 = dst_read.etag.strip('"')

            # Test MD5 sums
            if src_md5 != dst_md5:
                dst_out_exists = False
                err_msg = 'MD5 sums from %s and %s do not match, S3 file is '\
                          'somehow corrupted.\nTry re-uploading'
                break
            else:
                # It exists and matches, delete key
                dst_out_exists = True
                err_msg = 'File(s) uploaded successfully!'
                data_sink.bucket.delete_key(s3_key_path)

        # Return flag and err msg
        return dst_out_exists, err_msg

    # Test datasink node will write to base directory
    def test_datasink_node(self):
        '''
        Method to test the datasink running as its own node is working
        as producing the expected output

        Paramters
        ---------
        self : unittest.TestCase
            instance method inherits self automatically; instance
            variables are used in the method

        Returns
        -------
        None
            this method does not return any value, but performs an
            assertion on whether the expected output exists or not
        '''

        # Import packages

        # Init variables
        attr_folder = 'input_scan'
        container = 'test_datasink'
        data_sink = self.data_sink

        # Set up datasink
        data_sink.inputs.base_directory = self.base_dir
        data_sink.inputs.container = container
        # Feed input to input_file
        setattr(data_sink.inputs, attr_folder, self.in_file)

        # Run data_sink
        data_sink.run()

        # Check if output exists
        ds_out_exists, out_path = \
            self.check_output_exists(container, attr_folder)

        # Assert the output was produced as expected
        err_msg = 'Could not find output of datasink on disk: %s' % out_path
        self.assertTrue(ds_out_exists, msg=err_msg)

    # Test resource pool node -> datsink node workflow will write output
    def test_datasink_res_pool_wf(self):
        '''
        Method to test the datasink running in a nipype workflow; this
        mimics the behavior implemented in the C-PAC pipeline and uses
        a resource pool node to feed the datasink node to produce the
        output file

        Paramters
        ---------
        self : unittest.TestCase
            instance method inherits self automatically; instance
            variables are used in the method

        Returns
        -------
        None
            this method does not return any value, but performs an
            assertion on whether the expected output exists or not
        '''

        # Import packages
        import nipype.pipeline.engine as pe
        import nipype.interfaces.utility as niu

        # Init variables
        attr_folder = 'input_scan'
        container = 'test_datasink_res_pool_wf'
        data_sink = self.ds_node

        # Init workflow
        pipeline_wf = pe.Workflow(name='datasink_tester')
        pipeline_wf.base_dir = self.base_dir

        # Set up the dummy resource pool node
        res_pool_node = pe.Node(niu.IdentityInterface(fields=['out_file']),
                                name='res_pool')
        res_pool_node.inputs.out_file = self.in_file

        # Set up data sink node
        data_sink.inputs.base_directory = self.base_dir
        data_sink.inputs.container = container

        # Connect resource pool's out file to datasink node
        pipeline_wf.connect(res_pool_node, 'out_file', data_sink, attr_folder)

        # Run workflow
        pipeline_wf.run()

        # Check if output exists
        ds_out_exists, out_path = \
            self.check_output_exists(container, attr_folder)

        # Assert the output was produced as expected
        err_msg = 'Could not find output of datasink on disk: %s' % out_path
        self.assertTrue(ds_out_exists, msg=err_msg)

    # Test datasink node writes to S3
    def test_datasink_node_s3(self):
        '''
        Method to test the datasink running as its own node is working
        as producing the expected output

        Paramters
        ---------
        self : unittest.TestCase
            instance method inherits self automatically; instance
            variables are used in the method

        Returns
        -------
        None
            this method does not return any value, but performs an
            assertion on whether the expected output exists or not on
            AWS S3
        '''

        # Import packages
        import os

        from CPAC.utils import test_init

        # Init variables
        attr_folder = 'input_scan'
        container = 'test_datasink'
        data_sink = self.data_sink

        # Init AWS variables
        bucket_name = test_init.return_bucket_name()
        creds_path = self.creds_path
        s3_output_dir = os.path.join('s3://', bucket_name, 'data/unittest')

        # Set up datasink
        data_sink.inputs.base_directory = s3_output_dir
        data_sink.inputs.container = container
        data_sink.inputs.creds_path = creds_path

        # Feed input to input_file
        setattr(data_sink.inputs, attr_folder, self.in_file)

        # Run data_sink
        data_sink.run()

        # Check if output exists
        s3_out_exists, s3_out_msg = self.check_output_exists_s3(data_sink)

        # Assert the output was produced as expected
        self.assertTrue(s3_out_exists, msg=s3_out_msg)


# Make module executable
if __name__ == '__main__':
    unittest.main()
