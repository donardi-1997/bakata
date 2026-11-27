import json
from pathlib import Path
import unittest

class RoleTests(unittest.TestCase):
    def test_exact_secret_and_version(self):
        t=json.loads((Path(__file__).resolve().parents[1]/"infra/research-aws/credential-role.json").read_text())
        self.assertEqual(t["Parameters"]["EnableCredentialRole"]["Default"],"false")
        self.assertEqual(set(t["Resources"]),{"CredentialRole"})
        r=t["Resources"]["CredentialRole"]
        self.assertEqual(r["Condition"],"CredentialRoleEnabled")
        st=r["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
        self.assertEqual(len(st),1)
        self.assertEqual(st[0]["Action"],"secretsmanager:GetSecretValue")
        self.assertEqual(st[0]["Resource"],{"Ref":"ResearchSecretArn"})
        self.assertEqual(st[0]["Condition"]["StringEquals"],{"secretsmanager:VersionId":{"Ref":"SecretVersionId"},"secretsmanager:VersionStage":"AWSCURRENT","aws:ResourceAccount":{"Ref":"AWS::AccountId"}})
        trust=r["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]
        self.assertEqual(trust["Principal"],{"Service":"ecs-tasks.amazonaws.com"})
        self.assertEqual(trust["Condition"]["StringEquals"]["aws:SourceAccount"],{"Ref":"AWS::AccountId"})

if __name__=="__main__":
    unittest.main()
