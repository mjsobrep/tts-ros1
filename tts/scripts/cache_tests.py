
from __future__ import print_function

import sys
import json
import unittest

import rospy
import rostest

from tts.srv import Polly
from tts.srv import PollyResponse
from tts.srv import Synthesizer
from tts.srv import SynthesizerResponse

import pdb
pdb.set_trace()
import random


rospy.wait_for_service('synthesizer')
speech_synthesizer = rospy.ServiceProxy('synthesizer', Synthesizer)

random_end = random.randint()

# we need a random end to guarantee that the first test result won't be cached already
text = 'Mary has a little lamb, little lamb, little lamb. And a random int: {}'.format(random_end)
res = speech_synthesizer(text=text)
self.assertIsNotNone(res)
self.assertTrue(type(res) is SynthesizerResponse)

r = json.loads(res.result)
self.assertIn('Audio Type', r, 'result should contain audio type')
self.assertIn('Audio File', r, 'result should contain file path')
self.assertIn('Amazon Polly Response Metadata', r, 'result should contain metadata')

audio_type = r['Audio Type']
audio_file = r['Audio File']
md = r['Amazon Polly Response Metadata']
self.assertTrue("'HTTPStatusCode': 200," in md)
self.assertEqual('audio/ogg', audio_type)
self.assertTrue(audio_file.endswith('.ogg'))

import subprocess
o = subprocess.check_output(['file', audio_file], stderr=subprocess.STDOUT)
import re
m = re.search(r'.*Ogg data, Vorbis audi.*', o, flags=re.MULTILINE)
self.assertIsNotNone(m)
