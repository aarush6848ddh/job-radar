#!/usr/bin/env bash
#
# JobRadar AWS ingestion infrastructure.
#
# REVIEW BEFORE RUNNING. Nothing here executes until you run this script
# yourself. Steps marked [BILLABLE-ELIGIBLE] create real resources - they stay
# in free tier at this volume, but they are real AWS objects. Read every block.
#
# No SQS is created anywhere. The handoff to the M720q is the S3 object.
#
# Run on the M720q (Linux) so the built zip matches Lambda's Amazon Linux runtime.
# Requires: awscli v2 configured with an ADMIN profile (this bootstraps resources;
# the M720q's read-only runtime creds come later in Step 3, a DIFFERENT identity).

set -euo pipefail

# ----------------------------------------------------------------------------
# 0. Parameters - FILL THESE IN. Nothing below hardcodes secrets.
# ----------------------------------------------------------------------------
BUCKET="TODO-jobradar-raw-postings-UNIQUE"   # S3 names are GLOBALLY unique; add a suffix
REGION="us-east-1"                            # your region
NOTIFY_EMAIL="TODO@example.com"               # budget alert goes here (confirm the subscription email)

FUNCTION_NAME="jobradar-ingestion"
ROLE_NAME="jobradar-ingestion-role"
RULE_NAME="jobradar-ingestion-6h"
LOG_GROUP="/aws/lambda/${FUNCTION_NAME}"
ZIP_PATH="build/jobradar-ingestion.zip"

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
echo "Using account ${ACCOUNT_ID}, region ${REGION}, bucket ${BUCKET}"

# ----------------------------------------------------------------------------
# 1. [BILLABLE-ELIGIBLE] S3 bucket + 7-day lifecycle on raw-postings/
# ----------------------------------------------------------------------------
# us-east-1 must NOT pass LocationConstraint; every other region must.
if [ "$REGION" = "us-east-1" ]; then
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
else
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
    --create-bucket-configuration LocationConstraint="$REGION"
fi

# Lifecycle: expire anything under raw-postings/ after 7 days.
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" \
  --lifecycle-configuration '{
    "Rules": [{
      "ID": "expire-raw-postings-7d",
      "Filter": {"Prefix": "raw-postings/"},
      "Status": "Enabled",
      "Expiration": {"Days": 7}
    }]
  }'

# ----------------------------------------------------------------------------
# 2. Least-privilege execution role for the Lambda
#    (trust: lambda service; perms: PutObject on this bucket's raw-postings/
#     prefix only, plus writing to its own log group)
# ----------------------------------------------------------------------------
aws iam create-role --role-name "$ROLE_NAME" \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "lambda.amazonaws.com"},
      "Action": "sts:AssumeRole"
    }]
  }'

aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name jobradar-ingestion-inline \
  --policy-document "{
    \"Version\": \"2012-10-17\",
    \"Statement\": [
      {
        \"Effect\": \"Allow\",
        \"Action\": \"s3:PutObject\",
        \"Resource\": \"arn:aws:s3:::${BUCKET}/raw-postings/*\"
      },
      {
        \"Effect\": \"Allow\",
        \"Action\": [\"logs:CreateLogStream\", \"logs:PutLogEvents\"],
        \"Resource\": \"arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:${LOG_GROUP}:*\"
      }
    ]
  }"

# ----------------------------------------------------------------------------
# 3. Pre-create the log group with 7-day retention.
#    (If Lambda auto-creates it, retention defaults to "never expire".)
# ----------------------------------------------------------------------------
aws logs create-log-group --log-group-name "$LOG_GROUP" --region "$REGION"
aws logs put-retention-policy --log-group-name "$LOG_GROUP" --retention-in-days 7 --region "$REGION"

# ----------------------------------------------------------------------------
# 4. Build the deployment zip (deps + code + bundled config as sibling of handler).
#    Run on Linux (M720q). boto3 is NOT bundled - it's in the runtime.
# ----------------------------------------------------------------------------
rm -rf build && mkdir -p build/pkg
# Target the Lambda runtime's wheels EXPLICITLY (cp312 / manylinux x86_64) so the
# build does NOT depend on the M720q's own Python version. pyyaml ships a
# version-specific COMPILED wheel (_yaml); a cp39 build would fail to import under
# python3.12 on Lambda. requests/beautifulsoup4/soupsieve are pure-python (py3-none-any),
# and the code uses stdlib html.parser (no lxml), so pyyaml is the only binary concern.
pip install \
  --platform manylinux2014_x86_64 \
  --python-version 3.12 \
  --implementation cp \
  --only-binary=:all: \
  requests beautifulsoup4 pyyaml -t build/pkg
cp lambda/ingestion_handler.py build/pkg/
cp run_local.py schema.py build/pkg/
cp -r ingestion build/pkg/ingestion
cp -r config build/pkg/config            # sibling of the handler -> _CONFIG_DIR resolves
( cd build/pkg && zip -r "../jobradar-ingestion.zip" . -x '*.pyc' '*/__pycache__/*' )

# ----------------------------------------------------------------------------
# 5. [BILLABLE-ELIGIBLE] Create the Lambda function
# ----------------------------------------------------------------------------
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
aws lambda create-function \
  --function-name "$FUNCTION_NAME" \
  --runtime python3.12 \
  --handler ingestion_handler.handler \
  --role "$ROLE_ARN" \
  --zip-file "fileb://${ZIP_PATH}" \
  --timeout 60 \
  --memory-size 256 \
  --environment "Variables={POSTINGS_BUCKET=${BUCKET}}" \
  --region "$REGION"

# ----------------------------------------------------------------------------
# 5.5 CONTROLLED TEST INVOKE - run AFTER block 5, BEFORE block 6.
#     Catch any packaging/permission error on ONE manual invocation, not on the
#     first automatic trigger.
# ----------------------------------------------------------------------------
aws lambda invoke --function-name "$FUNCTION_NAME" --region "$REGION" \
  /tmp/jobradar-invoke.json
cat /tmp/jobradar-invoke.json                              # expect {"fetched":N,"kept":M,"key":"raw-postings/..."}
aws s3 ls "s3://${BUCKET}/raw-postings/"                   # confirm the object actually landed
aws logs tail "$LOG_GROUP" --region "$REGION" --since 10m  # confirm a clean run, no traceback

# ----------------------------------------------------------------------------
# 6. [BILLABLE-ELIGIBLE] EventBridge 6-hour schedule -> Lambda
# ----------------------------------------------------------------------------
aws events put-rule --name "$RULE_NAME" \
  --schedule-expression "rate(6 hours)" --region "$REGION"

aws lambda add-permission \
  --function-name "$FUNCTION_NAME" \
  --statement-id "${RULE_NAME}-invoke" \
  --action "lambda:InvokeFunction" \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:${REGION}:${ACCOUNT_ID}:rule/${RULE_NAME}" \
  --region "$REGION"

aws events put-targets --rule "$RULE_NAME" --region "$REGION" \
  --targets "Id=1,Arn=arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"

# ----------------------------------------------------------------------------
# 7. Zero-spend budget alert ($0.01 threshold). Budgets is a global service.
# ----------------------------------------------------------------------------
aws budgets create-budget \
  --account-id "$ACCOUNT_ID" \
  --budget '{
    "BudgetName": "jobradar-zero-spend",
    "BudgetLimit": {"Amount": "0.01", "Unit": "USD"},
    "TimeUnit": "MONTHLY",
    "BudgetType": "COST"
  }' \
  --notifications-with-subscribers "[{
    \"Notification\": {
      \"NotificationType\": \"ACTUAL\",
      \"ComparisonOperator\": \"GREATER_THAN\",
      \"Threshold\": 0,
      \"ThresholdType\": \"ABSOLUTE_VALUE\"
    },
    \"Subscribers\": [{\"SubscriptionType\": \"EMAIL\", \"Address\": \"${NOTIFY_EMAIL}\"}]
  }]"

# NOTE: Budgets EMAIL subscribers do NOT get a confirmation opt-in email (that's
# SNS behavior, not Budgets). Nothing arrives on creation - the alert only fires
# on ACTUAL spend > $0. So verify the notification is REGISTERED rather than
# waiting for a confirmation email that will never come:
aws budgets describe-notifications-for-budget \
  --account-id "$ACCOUNT_ID" --budget-name jobradar-zero-spend

echo "Done. Verify the schedule with:"
echo "  aws events list-targets-by-rule --rule ${RULE_NAME} --region ${REGION}"
