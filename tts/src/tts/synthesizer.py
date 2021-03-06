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

import os
import time
import json
import rospy
import hashlib
import sqlite3
import time
from optparse import OptionParser
from tts.srv import Synthesizer, SynthesizerResponse
from tts.srv import PollyResponse
from tts.db import DB


class SpeechSynthesizer:
    """This class serves as a ROS service node that should be an entry point of a TTS task.

    Although the current implementation uses Amazon Polly as the synthesis engine, it is not hard to let it support
    more heterogeneous engines while keeping the API the same.

    In order to support a variety of engines, the SynthesizerRequest was designed with flexibility in mind. It
    has two fields: text and metadata. Both are strings. In most cases, a user can ignore the metadata and call
    the service with some plain text. If the use case needs any control or engine-specific feature, the extra
    information can be put into the JSON-form metadata. This class will use the information when calling the engine.

    The decoupling of the synthesizer and the actual synthesis engine will benefit the users in many ways.

    First, a user will be able to use a unified interface to do the TTS job and have the freedom to use different
    engines available with no or very little change from the client side.

    Second, by applying some design patterns, the synthesizer can choose an engine dynamically. For example, a user
    may prefer to use Amazon Polly but is also OK with an offline solution when network is not reliable.

    Third, engines can be complicated, thus difficult to use. As an example, Amazon Polly supports dozens of parameters
    and is able to accomplish nontrivial synthesis jobs, but majority of the users never need those features. This
    class provides a clean interface with two parameters only, so that it is much easier and pleasant to use. If by
    any chance the advanced features are required, the user can always leverage the metadata field or even go to the
    backend engine directly.

    Also, from an engineering perspective, simple and decoupled modules are easier to maintain.

    This class supports two modes of using polly. It can either call a service node or use AmazonPolly as a library.

    Start the service node::

        $ rosrun tts synthesizer_node.py  # use default configuration
        $ rosrun tts synthesizer_node.py -e POLLY_LIBRARY  # will not call polly service node

    Call the service::

        $ rosservice call /synthesizer 'hello' ''
        $ rosservice call /synthesizer '<speak>hello</speak>' '"{\"text_type\":\"ssml\"}"'
    """

    class PollyViaNode:
        def __init__(self, polly_service_name='polly'):
            self.service_name = polly_service_name

        def __call__(self, **kwargs):
            rospy.loginfo('will call service {}'.format(self.service_name))
            from tts.srv import Polly
            rospy.wait_for_service(self.service_name)
            polly = rospy.ServiceProxy(self.service_name, Polly)
            return polly(polly_action='SynthesizeSpeech', **kwargs)

    class PollyDirect:
        def __init__(self):
            pass

        def __call__(self, **kwargs):
            rospy.loginfo('will import amazonpolly.AmazonPolly')
            from tts.amazonpolly import AmazonPolly
            node = AmazonPolly()
            return node.synthesize(**kwargs)

    class DummyEngine:
        """A dummy engine which exists to facilitate testing. Can either
        be set to act as if it is connected or disconnected. Will create files where
        they are expected, but they will not be actual audio files."""

        def __init__(self):
            self.connected = True
            self.file_size = 50000

        def __call__(self, **kwargs):
            """put a file at the specified location and return resonable dummy
            values. If not connected, fills in the Exception fields.

            Args:
                **kwarks: dictionary with fields: output_format, voice_id, sample_rate,
                          text_type, text, output_path

            Returns: A json version of a string with fields: Audio File, Audio Type, 
                Exception (if there is an exception), Traceback (if there is an exception), 
                and if succesful Amazon Polly Response Metadata
            """
            if self.connected:
                with open(kwargs['output_path'], 'wb') as f:
                    f.write(os.urandom(self.file_size))
                output_format = kwargs['OutputFormat'] if 'OutputFormat' in kwargs else 'ogg_vorbis'
                resp = json.dumps({
                    'Audio File': kwargs['output_path'],
                    'Audio Type': output_format,
                    'Amazon Polly Response Metadata': {'some header': 'some data'}
                    })
                return SynthesizerResponse(resp)
            else:
                current_dir = os.path.dirname(os.path.abspath(__file__))
                error_ogg_filename = 'connerror.ogg'
                error_details = {
                    'Audio File': os.path.join(current_dir, '../src/tts/data', error_ogg_filename),
                    'Audio Type': 'ogg',
                    'Exception': {
                        'dummy head': 'dummy val'
                        # 'Type': str(exc_type),
                        # 'Module': exc_type.__module__,
                        # 'Name': exc_type.__name__,
                        # 'Value': str(e),
                    },
                    'Traceback': 'some traceback'
                }
                return SynthesizerResponse(json.dumps(error_details))


        def set_connection(self, connected):
            """set the connection state

            Args:
                connected: boolean, whether to act connected or not
            """
            self.connected = connected

        def set_file_sizes(self, size):
            """Set the target file size for future files in bytes

            Args:
                size: the number of bytes to make the next files
            """
            self.file_size = size

    ENGINES = {
        'POLLY_SERVICE': PollyViaNode,
        'POLLY_LIBRARY': PollyDirect,
        'DUMMY': DummyEngine,
    }

    class BadEngineError(NameError):
        pass

    #TODO: expose this max_cache_bytes value to the roslaunch system (why is rosparam not used in this file?)
    def __init__(self, engine='POLLY_SERVICE', polly_service_name='polly', max_cache_bytes=100000000):
        if engine not in self.ENGINES:
            msg = 'bad engine {} which is not one of {}'.format(engine, ', '.join(SpeechSynthesizer.ENGINES.keys()))
            raise SpeechSynthesizer.BadEngineError(msg)

        engine_kwargs = {'polly_service_name': polly_service_name} if engine == 'POLLY_SERVICE' else {}
        self.engine = self.ENGINES[engine](**engine_kwargs)

        self.default_text_type = 'text'
        self.default_voice_id = 'Joanna'
        self.default_output_format = 'ogg_vorbis'

        self.max_cache_bytes = max_cache_bytes

    def _call_engine(self, **kw):
        """Call engine to do the job.

        If no output path is found from input, the audio
        file will be put into /tmp and the file name will have
        a prefix of the md5 hash of the text. If a filename is
        not given, the utterance is added to the cache. If a
        filename is specified, then we will assume that the
        file is being managed by the user and it will not
        be added to the cache.

        :param kw: what AmazonPolly needs to synthesize
        :return: response from AmazonPolly
        """
        if 'output_path' not in kw:
            tmp_filename = hashlib.md5(
                json.dumps(kw, sort_keys=True)).hexdigest()
            tmp_filepath = os.path.join(
                os.sep, 'tmp', 'voice_{}'.format(tmp_filename))
            kw['output_path'] = os.path.abspath(tmp_filepath)
            rospy.loginfo('managing file with name: {}'.format(tmp_filename))

            # because the hash will include information about any file ending choices, we only
            # need to look at the hash itself.
            db = DB()
            db_search_result = db.ex(
                'SELECT file, audio_type FROM cache WHERE hash=?', tmp_filename).fetchone()
            current_time = time.time()
            file_found = False
            if db_search_result:  # then there is data
                # check if the file exists, if not, remove from db
                # TODO: add a test that deletes a file without telling the db and tries to synthesize it
                if os.path.exists(db_search_result['file']):
                    file_found = True
                    db.ex('update  cache set last_accessed=? where hash=?',
                          current_time, tmp_filename)
                    synth_result = PollyResponse(json.dumps({
                        'Audio File': db_search_result['file'],
                        'Audio Type': db_search_result['audio_type'],
                        'Amazon Polly Response Metadata': ''
                    }))
                    rospy.loginfo('audio file was already cached at: %s',
                                  db_search_result['file'])
                else:
                    rospy.logwarn(
                        'A file in the database did not exist on the disk, removing from db')
                    db.remove_file(db_search_result['file'])
            if not file_found:  # havent cached this yet
                rospy.loginfo('Caching file')
                synth_result = self.engine(**kw)
                res_dict = json.loads(synth_result.result)
                if 'Exception' not in res_dict:
                    file_name = res_dict['Audio File']
                    if file_name:
                        file_size = os.path.getsize(file_name)
                        db.ex('''insert into cache(
                            hash, file, audio_type, last_accessed,size)
                            values (?,?,?,?,?)''', tmp_filename, file_name,
                              res_dict['Audio Type'], current_time, file_size)
                        rospy.loginfo(
                            'generated new file, saved to %s and cached', file_name)
                        # make sure the cache hasn't grown too big
                        while db.get_size() > self.max_cache_bytes and db.get_num_files() > 1:
                            remove_res = db.ex(
                                'select file, min(last_accessed), size from cache'
                            ).fetchone()
                            db.remove_file(remove_res['file'])
                            rospy.loginfo('removing %s to maintain cache size, new size: %i',
                                          remove_res['file'], db.get_size())
        else:
            synth_result = self.engine(**kw)

        return synth_result

    def _parse_request_or_raise(self, request):
        """It will raise if request is malformed.

        :param request: an instance of SynthesizerRequest
        :return: a dict
        """
        md = json.loads(request.metadata) if request.metadata else {}

        md['output_format'] = md.get('output_format', self.default_output_format)
        md['voice_id'] = md.get('voice_id', self.default_voice_id)
        md['sample_rate'] = md.get('sample_rate', '16000' if md['output_format'].lower() == 'pcm' else '22050')
        md['text_type'] = md.get('text_type', self.default_text_type)
        md['text'] = request.text

        return md

    def _node_request_handler(self, request):
        """The callback function for processing service request.

        It never raises. If anything unexpected happens, it will return a SynthesizerResponse with the exception.

        :param request: an instance of SynthesizerRequest
        :return: a SynthesizerResponse
        """
        rospy.loginfo(request)
        try:
            kws = self._parse_request_or_raise(request)
            res = self._call_engine(**kws).result

            return SynthesizerResponse(res)
        except Exception as e:
            return SynthesizerResponse('Exception: {}'.format(e))

    def start(self, node_name='synthesizer_node', service_name='synthesizer'):
        """The entry point of a ROS service node.

        :param node_name: name of ROS node
        :param service_name:  name of ROS service
        :return: it doesn't return
        """
        rospy.init_node(node_name)

        service = rospy.Service(service_name, Synthesizer, self._node_request_handler)

        rospy.loginfo('{} running: {}'.format(node_name, service.uri))

        rospy.spin()


def main():
    usage = '''usage: %prog [options]
    '''

    parser = OptionParser(usage)

    parser.add_option("-n", "--node-name", dest="node_name", default='synthesizer_node',
                      help="name of the ROS node",
                      metavar="NODE_NAME")
    parser.add_option("-s", "--service-name", dest="service_name", default='synthesizer',
                      help="name of the ROS service",
                      metavar="SERVICE_NAME")
    parser.add_option("-e", "--engine", dest="engine", default='POLLY_SERVICE',
                      help="name of the synthesis engine",
                      metavar="ENGINE")
    parser.add_option("-p", "--polly-service-name", dest="polly_service_name", default='polly',
                      help="name of the polly service",
                      metavar="POLLY_SERVICE_NAME")

    (options, args) = parser.parse_args()

    node_name = options.node_name
    service_name = options.service_name
    engine = options.engine
    polly_service_name = options.polly_service_name

    if engine == 'POLLY_SERVICE':
        synthesizer = SpeechSynthesizer(engine=engine, polly_service_name=polly_service_name)
    else:
        synthesizer = SpeechSynthesizer(engine=engine)
    synthesizer.start(node_name=node_name, service_name=service_name)


if __name__ == "__main__":
    main()
