import json
import unittest
from unittest.mock import Mock

from intelligence.research_credentials import SecretBinding,load_pinned,parse_secret,SCHEMA
from intelligence.research_egress import approved_destination


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.arn="arn:aws:secretsmanager:us-east-1:123456789012:secret:bakata/research/dropify/pilot-Ab1234"
        self.version="a"*32
        self.binding=SecretBinding(self.arn,self.version,"123456789012","7")
        self.raw=json.dumps({"schema":SCHEMA,"store_id":"7","token":"fixture-secret-canary"})
        self.response={"ARN":self.arn,"VersionId":self.version,"VersionStages":["AWSCURRENT"],"SecretString":self.raw}

    def test_pinned_read(self):
        client=Mock()
        client.get_secret_value.return_value=self.response
        result=load_pinned(client,self.binding)
        self.assertEqual(result.store,"7")
        self.assertEqual(result.token,"fixture-secret-canary")
        self.assertNotIn(result.token,repr(result))
        client.get_secret_value.assert_called_once_with(SecretId=self.arn,VersionId=self.version,VersionStage="AWSCURRENT")

    def test_wrong_binding(self):
        for arn,version,account,store in [(self.arn,self.version,"000000000000","7"),
            (self.arn.replace("us-east-1","us-west-2"),self.version,"123456789012","7"),
            (self.arn.replace("research","production"),self.version,"123456789012","7"),
            (self.arn,"latest","123456789012","7"),(self.arn,self.version,"123456789012","0")]:
            with self.subTest(arn=arn,version=version):
                with self.assertRaises(ValueError): SecretBinding(arn,version,account,store)

    def test_mismatch_never_falls_back(self):
        for changes in [{"ARN":self.arn+"x"},{"VersionId":"b"*32},{"VersionStages":["AWSPREVIOUS"]},
                        {"SecretBinary":b"x"},{"SecretString":self.raw.replace('"7"','"8"')}]:
            client=Mock()
            client.get_secret_value.return_value=dict(self.response,**changes)
            with self.assertRaisesRegex(ValueError,"Pinned research credential unavailable"):
                load_pinned(client,self.binding)
            self.assertEqual(client.get_secret_value.call_count,1)

    def test_secret_envelope(self):
        for raw in [self.raw.replace("fixture-secret-canary","bad token"),self.raw.replace("fixture-secret-canary","x"*1001),
                    self.raw.replace('"token":','"token":"duplicate","token":'),
                    self.raw[:-1]+',"extra":true}',"{}",None,b"binary"]:
            with self.assertRaisesRegex(ValueError,"Invalid research credential envelope") as ctx:
                parse_secret(raw,"7")
            self.assertNotIn("fixture-secret-canary",str(ctx.exception))

    def test_exception_redacted(self):
        client=Mock()
        client.get_secret_value.side_effect=RuntimeError("fixture-secret-canary")
        with self.assertRaises(ValueError) as ctx: load_pinned(client,self.binding)
        self.assertNotIn("fixture-secret-canary",str(ctx.exception))
        self.assertTrue(ctx.exception.__suppress_context__)
        self.assertEqual(client.get_secret_value.call_count,1)


class EgressTests(unittest.TestCase):
    def test_only_exact_connect_and_public_addresses(self):
        self.assertEqual(approved_destination("CONNECT","api.dropi.co:443",["8.8.8.8","8.8.8.8","1.1.1.1"]),("8.8.8.8","1.1.1.1"))

    def test_wrong_authorities(self):
        for method,authority in [("GET","api.dropi.co:443"),("CONNECT","api.dropi.co:80"),
            ("CONNECT","api.dropi.co.evil.invalid:443"),("CONNECT","api.dropi.co.:443"),("CONNECT","user@api.dropi.co:443"),
            ("CONNECT","api.dropi.co:443/path"),("CONNECT","8.8.8.8:443")]:
            with self.assertRaises(ValueError): approved_destination(method,authority,["8.8.8.8"])

    def test_nonpublic_and_mixed_dns_denied(self):
        for ip in ["127.0.0.1","10.0.0.1","169.254.169.254","100.64.0.1","192.0.2.1","224.0.0.1","0.0.0.0","::1","::ffff:8.8.8.8","2001:4860:4860::8888","invalid"]:
            with self.subTest(ip=ip):
                with self.assertRaises(ValueError): approved_destination("CONNECT","api.dropi.co:443",["8.8.8.8",ip])
        for answers in [[],["8.8.8.8"]*17,"8.8.8.8"]:
            with self.assertRaises(ValueError): approved_destination("CONNECT","api.dropi.co:443",answers)


if __name__=="__main__":
    unittest.main()
