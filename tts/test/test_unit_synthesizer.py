#!/usr/bin/env python

# Copyright (c) 2018, Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may not use this file except in compliance with the License.
# A copy of the License is located at
#
#  http://aws.amazon.com/apache2.0
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.

from __future__ import print_function

from mock import patch, MagicMock # python2 uses backport of unittest.mock(docs.python.org/3/library/unittest.mock.html)
import unittest


class TestSynthesizer(unittest.TestCase):

    def setUp(self):
        """important: import tts which is a relay package::

            devel/lib/python2.7/dist-packages/
            +-- tts
            |   +-- __init__.py
            +-- ...

        per http://docs.ros.org/api/catkin/html/user_guide/setup_dot_py.html:

        A relay package is a folder with an __init__.py folder and nothing else.
        Importing this folder in python will execute the contents of __init__.py,
        which will in turn import the original python modules in the folder in
        the sourcespace using the python exec() function.
        """
        import tts
        self.assertIsNotNone(tts)

    def test_init(self):
        from tts.synthesizer import SpeechSynthesizer
        speech_synthesizer = SpeechSynthesizer()
        self.assertEqual('text', speech_synthesizer.default_text_type)

    @patch('tts.amazonpolly.AmazonPolly')
    def test_good_synthesis_with_mostly_default_args_using_polly_lib(self, polly_class_mock):
        polly_obj_mock = MagicMock()
        polly_class_mock.return_value = polly_obj_mock

        test_text = 'hello'
        test_metadata = '''
            {
                "output_path": "/tmp/test"
            }
        '''
        expected_polly_synthesize_args = {
            'output_format': 'ogg_vorbis',
            'voice_id': 'Joanna',
            'sample_rate': '22050',
            'text_type': 'text',
            'text': test_text,
            'output_path': "/tmp/test"
        }

        from tts.synthesizer import SpeechSynthesizer
        from tts.srv import SynthesizerRequest
        speech_synthesizer = SpeechSynthesizer(engine='POLLY_LIBRARY')
        request = SynthesizerRequest(text=test_text, metadata=test_metadata)
        response = speech_synthesizer._node_request_handler(request)

        self.assertGreater(polly_class_mock.call_count, 0)
        polly_obj_mock.synthesize.assert_called_with(**expected_polly_synthesize_args)

        self.assertEqual(response.result, polly_obj_mock.synthesize.return_value.result)

    @patch('tts.amazonpolly.AmazonPolly')
    def test_synthesis_with_bad_metadata_using_polly_lib(self, polly_class_mock):
        polly_obj_mock = MagicMock()
        polly_class_mock.return_value = polly_obj_mock

        test_text = 'hello'
        test_metadata = '''I am no JSON'''

        from tts.synthesizer import SpeechSynthesizer
        from tts.srv import SynthesizerRequest
        speech_synthesizer = SpeechSynthesizer(engine='POLLY_LIBRARY')
        request = SynthesizerRequest(text=test_text, metadata=test_metadata)
        response = speech_synthesizer._node_request_handler(request)

        self.assertTrue(response.result.startswith('Exception: '))

    @patch('tts.amazonpolly.AmazonPolly')
    def test_bad_engine(self, polly_class_mock):
        polly_obj_mock = MagicMock()
        polly_class_mock.return_value = polly_obj_mock

        ex = None

        from tts.synthesizer import SpeechSynthesizer
        try:
            SpeechSynthesizer(engine='NON-EXIST ENGINE')
        except Exception as e:
            ex = e

        self.assertTrue(isinstance(ex, SpeechSynthesizer.BadEngineError))

    def test_cli_help_message(self):
        import os
        source_file_dir = os.path.dirname(os.path.abspath(__file__))
        synthersizer_path = os.path.join(source_file_dir, '..', 'scripts', 'synthesizer_node.py')
        import subprocess
        o = subprocess.check_output(['python', synthersizer_path, '-h'])
        self.assertTrue(str(o).startswith('Usage: '))

    @patch('tts.synthesizer.SpeechSynthesizer')
    def test_cli_engine_dispatching_1(self, speech_synthesizer_class_mock):
        import sys
        with patch.object(sys, 'argv', ['synthesizer_node.py']):
            import tts.synthesizer
            tts.synthesizer.main()
            speech_synthesizer_class_mock.assert_called_with(engine='POLLY_SERVICE', polly_service_name='polly')
            speech_synthesizer_class_mock.return_value.start.assert_called_with(node_name='synthesizer_node',
                                                                               service_name='synthesizer')

    @patch('tts.synthesizer.SpeechSynthesizer')
    def test_cli_engine_dispatching_2(self, speech_synthesizer_class_mock):
        import sys
        with patch.object(sys, 'argv', ['synthesizer_node.py', '-e', 'POLLY_LIBRARY']):
            from tts import synthesizer
            synthesizer.main()
            speech_synthesizer_class_mock.assert_called_with(engine='POLLY_LIBRARY')
            self.assertGreater(speech_synthesizer_class_mock.return_value.start.call_count, 0)

    @patch('tts.synthesizer.SpeechSynthesizer')
    def test_cli_engine_dispatching_3(self, speech_synthesizer_class_mock):
        import sys
        with patch.object(sys, 'argv', ['synthesizer_node.py', '-p', 'apolly']):
            from tts import synthesizer
            synthesizer.main()
            speech_synthesizer_class_mock.assert_called_with(engine='POLLY_SERVICE', polly_service_name='apolly')
            self.assertGreater(speech_synthesizer_class_mock.return_value.start.call_count, 0)

    def test_repeated_synthesis(self):
        from tts.db import DB
        from tts.synthesizer import SpeechSynthesizer
        from tts.srv import SynthesizerRequest
        import uuid

        db = DB()
        init_num_files = db.get_num_files()

        new_text = uuid.uuid4().hex
        for i in range(4):
            speech_synthesizer = SpeechSynthesizer(engine='DUMMY')
            request = SynthesizerRequest(text=new_text, metadata={})
            response = speech_synthesizer._node_request_handler(request)

            self.assertEqual(db.get_num_files(), init_num_files + 1)

        
    def test_multiple_novel(self):
        from tts.db import DB
        from tts.synthesizer import SpeechSynthesizer
        from tts.srv import SynthesizerRequest
        import uuid

        db = DB()
        init_num_files = db.get_num_files()
        for i in range(4):
            speech_synthesizer = SpeechSynthesizer(engine='DUMMY')
            request = SynthesizerRequest(text=uuid.uuid4().hex, metadata={})
            response = speech_synthesizer._node_request_handler(request)

            self.assertEqual(db.get_num_files(), init_num_files + i + 1)

    def test_lost_file(self):
        from tts.db import DB
        from tts.synthesizer import SpeechSynthesizer
        from tts.srv import SynthesizerRequest
        import uuid
        import os
        import json

        db = DB()
        init_num_files = db.get_num_files()
        req_text=uuid.uuid4().hex

        speech_synthesizer = SpeechSynthesizer(engine='DUMMY')

        request = SynthesizerRequest(text=req_text, metadata={})
        response = speech_synthesizer._node_request_handler(request)
        res_dict = json.loads(response.result)
        audio_file1 = res_dict['Audio File']

        self.assertEqual(db.get_num_files(), init_num_files + 1)

        os.remove(audio_file1)

        request = SynthesizerRequest(text=req_text, metadata={})
        response = speech_synthesizer._node_request_handler(request)
        res_dict = json.loads(response.result)
        audio_file2 = res_dict['Audio File']

        self.assertEqual(db.get_num_files(), init_num_files + 1)
        self.assertEqual(audio_file1, audio_file2)
        self.assertTrue(os.path.exists(audio_file2))

    def test_no_connection_novel(self):
        from tts.db import DB
        from tts.synthesizer import SpeechSynthesizer
        from tts.srv import SynthesizerRequest
        import uuid

        db = DB()
        init_num_files = db.get_num_files()

        speech_synthesizer = SpeechSynthesizer(engine='DUMMY')
        speech_synthesizer.engine.set_connection(False)

        request = SynthesizerRequest(text=uuid.uuid4().hex, metadata={})
        response = speech_synthesizer._node_request_handler(request)

        self.assertEqual(db.get_num_files(), init_num_files)

    def test_no_connection_existing(self):
        from tts.db import DB
        from tts.synthesizer import SpeechSynthesizer
        from tts.srv import SynthesizerRequest
        import uuid
        import json

        target_text = uuid.uuid4().hex

        speech_synthesizer = SpeechSynthesizer(engine='DUMMY')
        request = SynthesizerRequest(text=target_text, metadata={})
        response = speech_synthesizer._node_request_handler(request)
        res_dict = json.loads(response.result)
        audio_file1 = res_dict['Audio File']

        speech_synthesizer.engine.set_connection(False)

        speech_synthesizer = SpeechSynthesizer(engine='DUMMY')
        request = SynthesizerRequest(text=target_text, metadata={})
        response = speech_synthesizer._node_request_handler(request)
        res_dict = json.loads(response.result)
        audio_file2 = res_dict['Audio File']

        self.assertEqual(audio_file1, audio_file2)

    def test_file_cleanup(self):
        from tts.db import DB
        from tts.synthesizer import SpeechSynthesizer
        from tts.srv import SynthesizerRequest
        import uuid
        import json
        import os

        db = DB()
        speech_synthesizer = SpeechSynthesizer(engine='DUMMY',max_cache_bytes=401)
        speech_synthesizer.engine.set_file_sizes(100)

        request = SynthesizerRequest(text=uuid.uuid4().hex, metadata={})
        response = speech_synthesizer._node_request_handler(request)
        res_dict = json.loads(response.result)
        audio_file1 = res_dict['Audio File']
        self.assertTrue(os.path.exists(audio_file1))

        for i in range(5):
            request = SynthesizerRequest(text=uuid.uuid4().hex, metadata={})
            response = speech_synthesizer._node_request_handler(request)

        self.assertFalse(os.path.exists(audio_file1))

    def test_big_db(self):
        from tts.db import DB
        from tts.synthesizer import SpeechSynthesizer
        from tts.srv import SynthesizerRequest
        import uuid

        db = DB()
        speech_synthesizer = SpeechSynthesizer(engine='DUMMY',max_cache_bytes=401)
        speech_synthesizer.engine.set_file_sizes(100)

        for i in range(20):
            request = SynthesizerRequest(text=uuid.uuid4().hex, metadata={})
            response = speech_synthesizer._node_request_handler(request)

        self.assertEqual(db.get_num_files(), 4)

        speech_synthesizer = SpeechSynthesizer(engine='DUMMY',max_cache_bytes=40001)
        speech_synthesizer.engine.set_file_sizes(1000)

        for i in range(80):
            request = SynthesizerRequest(text=uuid.uuid4().hex, metadata={})
            response = speech_synthesizer._node_request_handler(request)

        self.assertEqual(db.get_num_files(), 40)

    def test_file_cleanup_priority(self):
        from tts.db import DB
        from tts.synthesizer import SpeechSynthesizer
        from tts.srv import SynthesizerRequest
        import uuid
        import json
        import os

        db = DB()
        speech_synthesizer = SpeechSynthesizer(engine='DUMMY',max_cache_bytes=401)
        speech_synthesizer.engine.set_file_sizes(100)

        special_text = uuid.uuid4().hex
        request = SynthesizerRequest(text=special_text, metadata={})
        response = speech_synthesizer._node_request_handler(request)
        res_dict = json.loads(response.result)
        audio_file1 = res_dict['Audio File']
        self.assertTrue(os.path.exists(audio_file1))

        special_text2 = uuid.uuid4().hex
        request = SynthesizerRequest(text=special_text2, metadata={})
        response = speech_synthesizer._node_request_handler(request)
        res_dict = json.loads(response.result)
        audio_file2 = res_dict['Audio File']
        self.assertTrue(os.path.exists(audio_file2))

        for z in range(2):
            for i in range(2):
                request = SynthesizerRequest(text=uuid.uuid4().hex, metadata={})
                response = speech_synthesizer._node_request_handler(request)
            request = SynthesizerRequest(text=special_text, metadata={})
            response = speech_synthesizer._node_request_handler(request)
            res_dict = json.loads(response.result)
            audio_file1 = res_dict['Audio File']

        self.assertFalse(os.path.exists(audio_file2))
        self.assertTrue(os.path.exists(audio_file1))


if __name__ == '__main__':
    import rosunit
    rosunit.unitrun('tts', 'unittest-synthesizer', TestSynthesizer)
