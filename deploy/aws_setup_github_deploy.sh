#!/usr/bin/env bash
# One-time AWS setup for the GitHub Deploy button (.github/workflows/deploy.yml).
# Run it once in AWS CloudShell (signed in to the AWS console as the account owner, region London):
#   bash aws_setup_github_deploy.sh
# Safe to run again: whatever already exists is left as it is.
#
# What it makes:
#   1. Two private image stores in Amazon ECR (London): ledgermind-backend, ledgermind-frontend
#      (only the last 10 images of each are kept, so storage stays at a few pence a month)
#   2. GitHub as a trusted sign-in for AWS (no AWS keys are ever stored in GitHub)
#   3. A role GitHub uses, only from the main branch of dhruv608/finance-flow, that can only:
#      push to those two image stores, and run the deploy command on the LedgerMind server
#   4. The server's own role may read those images, and be reached by AWS Systems Manager (to run the deploy)
set -euo pipefail

REGION=eu-west-2
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REPO_GITHUB="dhruv608/finance-flow"
# GitHub's sign-in label carries the owner and repo IDs (seen in the Deploy run's first step): main branch only
GITHUB_SUB="repo:dhruv608@191451087/finance-flow@1392413193:ref:refs/heads/main"
INSTANCE_ID=i-026198d03f29b0664
SERVER_ROLE=ledgermind-server
DEPLOY_ROLE=ledgermind-github-deploy
echo "Account $ACCOUNT, region $REGION"

# 1. Image stores
for name in ledgermind-backend ledgermind-frontend; do
  aws ecr describe-repositories --region $REGION --repository-names $name >/dev/null 2>&1 ||
    aws ecr create-repository --region $REGION --repository-name $name \
      --image-scanning-configuration scanOnPush=true --encryption-configuration encryptionType=AES256 >/dev/null
  aws ecr put-lifecycle-policy --region $REGION --repository-name $name --lifecycle-policy-text '{
    "rules": [{"rulePriority": 1, "description": "Keep the last 10 images",
               "selection": {"tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 10},
               "action": {"type": "expire"}}]}' >/dev/null
  echo "Image store ready: $name"
done

# 2. GitHub as a trusted sign-in
OIDC_ARN="arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com"
aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" >/dev/null 2>&1 ||
  aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 >/dev/null
echo "GitHub sign-in ready"

# 3. The role GitHub uses (main branch of this repo only)
cat > /tmp/trust.json <<EOF
{"Version": "2012-10-17", "Statement": [{
  "Effect": "Allow",
  "Principal": {"Federated": "$OIDC_ARN"},
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                     "token.actions.githubusercontent.com:sub": "$GITHUB_SUB"}}}]}
EOF
aws iam get-role --role-name $DEPLOY_ROLE >/dev/null 2>&1 ||
  aws iam create-role --role-name $DEPLOY_ROLE --assume-role-policy-document file:///tmp/trust.json \
    --description "GitHub Deploy button for LedgerMind" >/dev/null
aws iam update-assume-role-policy --role-name $DEPLOY_ROLE --policy-document file:///tmp/trust.json

cat > /tmp/deploy-policy.json <<EOF
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
  {"Effect": "Allow",
   "Action": ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
              "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"],
   "Resource": ["arn:aws:ecr:$REGION:$ACCOUNT:repository/ledgermind-backend",
                "arn:aws:ecr:$REGION:$ACCOUNT:repository/ledgermind-frontend"]},
  {"Effect": "Allow", "Action": "ssm:SendCommand",
   "Resource": ["arn:aws:ec2:$REGION:$ACCOUNT:instance/$INSTANCE_ID",
                "arn:aws:ssm:$REGION::document/AWS-RunShellScript"]},
  {"Effect": "Allow", "Action": ["ssm:GetCommandInvocation", "ssm:ListCommandInvocations"], "Resource": "*"}]}
EOF
aws iam put-role-policy --role-name $DEPLOY_ROLE --policy-name deploy --policy-document file:///tmp/deploy-policy.json
echo "GitHub deploy role ready: arn:aws:iam::$ACCOUNT:role/$DEPLOY_ROLE"

# 4. The server: read the images, and be reachable by Systems Manager
aws iam attach-role-policy --role-name $SERVER_ROLE \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
aws iam attach-role-policy --role-name $SERVER_ROLE \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
echo "Server role ready (the server shows up in Systems Manager within a few minutes)"

echo
echo "Done. Next: push the code, then GitHub > Actions > Deploy > Run workflow."
