import tts
from tts.synthesizer import SpeechSynthesizer
from tts.srv import SynthesizerRequest
import pdb

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

pdb.set_trace()
speech_synthesizer = SpeechSynthesizer(engine='POLLY_LIBRARY')
request = SynthesizerRequest(text=test_text, metadata=test_metadata)
response = speech_synthesizer._node_request_handler(request)
