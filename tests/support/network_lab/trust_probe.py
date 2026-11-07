"""Negative trust test of the real native SIP TLS policy, with synthetic devices."""
import json
import os
from pathlib import Path
import sys
import time

from terminal import SyntheticEngine
from zmala_terminal.common.configuration import Configuration


def main():
    identity, failure = sys.argv[1:3]
    credentials = json.loads(Path(f'/lab/{identity}.json').read_text())
    configuration = Configuration({'server_url':'https://10.231.100.15:443',
        'device_id':identity, 'device_token':credentials['token']}, '/tmp/trust-config.json')
    config = configuration.fetch(persist=False)
    if failure == 'ca':
        os.environ['SSL_CERT_FILE'] = '/etc/ssl/certs/ca-certificates.crt'
    elif failure == 'name':
        # /etc/hosts contains this lab-only alias; its name is absent from the certificate.
        config['sip']['proxy'] = 'sip:wrong.lab:443;transport=tls'
    else:
        raise ValueError('Unknown negative trust case')
    registrations = []
    engine = SyntheticEngine(config, lambda *args: None, registrations.append, profile='trust-probe')
    try:
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            engine.iterate()
            assert not engine.registered, 'Native TLS accepted an untrusted endpoint'
            time.sleep(.01)
        assert False in registrations, 'Native registration failure was not reported'
        print('ZMALA_TRUST_RESULT='+json.dumps({'case':failure, 'registration_rejected':True}), flush=True)
    finally:
        engine.close()
        configuration.deactivate()


if __name__ == '__main__':
    main()
