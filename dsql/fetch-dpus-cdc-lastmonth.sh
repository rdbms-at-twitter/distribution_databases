#!/bin/bash
#
# fetch-dpus-cdc-lastmonth.sh - Aurora DSQL DPU Cost Report (Previous Month)
#
# Description:
#   Same as fetch-dpus-cdc-v3.sh but reports the PREVIOUS month's data.
#   Useful for comparing CloudWatch-based cost estimates against Cost Explorer actuals.
#
# Usage:
#   ./fetch-dpus-cdc-lastmonth.sh <cluster-id> [region]
#
# Examples:
#   ./fetch-dpus-cdc-lastmonth.sh lmabug6a7xcqjqohr
#   ./fetch-dpus-cdc-lastmonth.sh lmabug6a7xcqjqohr ap-northeast-1
#
# Pricing source: https://aws.amazon.com/aurora/dsql/pricing/
# Last updated: 2026-07-27
#

set -euo pipefail
shopt -s failglob

# ============================================================
# Region-based pricing definition
# Format: "DPU_PER_1M  STORAGE_PER_GB_MONTH  FREE_DPU  FREE_STORAGE_GB"
# ============================================================
declare -A PRICING
PRICING[us-east-1]="8.00 0.33 100000 1"
PRICING[us-east-2]="8.00 0.33 100000 1"
PRICING[us-west-2]="8.00 0.33 100000 1"
PRICING[eu-west-1]="9.20 0.38 100000 1"
PRICING[eu-central-1]="9.20 0.38 100000 1"
PRICING[ap-southeast-1]="9.60 0.40 100000 1"
PRICING[ap-northeast-1]="10.40 0.43 100000 1"

DEFAULT_REGION="us-east-1"

# ============================================================
# Argument parsing
# ============================================================
if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Usage: $0 <cluster-id> [region]"
    echo ""
    echo "  Default region: $DEFAULT_REGION"
    echo "  Supported regions: ${!PRICING[*]}"
    exit 1
fi

CLUSTER_ID=$1
REGION=${2:-$DEFAULT_REGION}

if [[ -z "${PRICING[$REGION]+x}" ]]; then
    echo "ERROR: Unsupported region '$REGION'"
    echo "Supported: ${!PRICING[*]}"
    exit 1
fi

read -r DPU_PRICE STORAGE_PRICE FREE_TIER_DPU FREE_TIER_STORAGE_GB <<< "${PRICING[$REGION]}"

# ============================================================
# Time range (PREVIOUS month)
# ============================================================
# Calculate first day of last month and first day of current month
START_TIME=$(date -u -d "$(date -u +%Y-%m-01) -1 month" +"%Y-%m-01T00:00:00Z" 2>/dev/null \
    || date -u -v-1m -v1d +"%Y-%m-01T00:00:00Z")
END_TIME=$(date -u +"%Y-%m-01T00:00:00Z")
MONTH_LABEL=$(date -u -d "$(date -u +%Y-%m-01) -1 month" +"%Y-%m" 2>/dev/null \
    || date -u -v-1m +"%Y-%m")

# ============================================================
# Header
# ============================================================
ESC=$(printf '\033')
REV="${ESC}[7m"
RESET="${ESC}[0m"

echo ""
printf '  %b%s%b\n' "$REV" "                                                              " "$RESET"
printf '  %b%s%b\n' "$REV" "     Aurora DSQL — Previous Month DPU Cost Report             " "$RESET"
printf '  %b%s%b\n' "$REV" "                                                              " "$RESET"
echo ""
echo "  Cluster:  $CLUSTER_ID"
echo "  Region:   $REGION"
echo "  Period:   $START_TIME → $END_TIME"
echo "  Pricing:  \$$DPU_PRICE/1M DPU  |  \$$STORAGE_PRICE/GB-month  |  Free: ${FREE_TIER_DPU} DPU + ${FREE_TIER_STORAGE_GB} GB"
echo ""

# ============================================================
# Fetch daily DPU metrics
# ============================================================
fetch_metric() {
    aws cloudwatch get-metric-statistics \
        --namespace "AWS/AuroraDSQL" \
        --metric-name "$1" \
        --dimensions Name=ClusterId,Value=$CLUSTER_ID \
        --start-time "$START_TIME" \
        --end-time "$END_TIME" \
        --period 86400 \
        --statistics Sum \
        --region "$REGION" \
        --output json
}

# StreamDPU requires both ClusterId and StreamId dimensions.
fetch_stream_metric() {
    local STREAM_ID
    STREAM_ID=$(aws dsql list-streams --cluster-identifier "$CLUSTER_ID" --region "$REGION" \
        --query 'streams[0].streamIdentifier' --output text 2>/dev/null)

    if [[ -z "$STREAM_ID" || "$STREAM_ID" == "None" ]]; then
        echo '{"Datapoints":[]}'
        return
    fi

    aws cloudwatch get-metric-statistics \
        --namespace "AWS/AuroraDSQL" \
        --metric-name "StreamDPU" \
        --dimensions Name=ClusterId,Value="$CLUSTER_ID" Name=StreamId,Value="$STREAM_ID" \
        --start-time "$START_TIME" \
        --end-time "$END_TIME" \
        --period 86400 \
        --statistics Sum \
        --region "$REGION" \
        --output json
}

TOTAL_DPU_JSON=$(fetch_metric "TotalDPU")
READ_DPU_JSON=$(fetch_metric "ReadDPU")
WRITE_DPU_JSON=$(fetch_metric "WriteDPU")
COMPUTE_DPU_JSON=$(fetch_metric "ComputeDPU")
STREAM_DPU_JSON=$(fetch_stream_metric)

# ============================================================
# Build daily table (merge all metrics by date)
# ============================================================
DAILY_TABLE=$(jq -n \
    --argjson total "$TOTAL_DPU_JSON" \
    --argjson read "$READ_DPU_JSON" \
    --argjson write "$WRITE_DPU_JSON" \
    --argjson compute "$COMPUTE_DPU_JSON" \
    --argjson stream "$STREAM_DPU_JSON" '
def to_map:
    [.Datapoints[] | {(.Timestamp | split("T")[0]): .Sum}] | add // {};

($total | to_map) as $t |
($read | to_map) as $r |
($write | to_map) as $w |
($compute | to_map) as $c |
($stream | to_map) as $s |

([$t, $r, $w, $c, $s] | map(keys) | add | unique | sort) as $dates |

$dates | map({
    date: .,
    read: ($r[.] // 0),
    write: ($w[.] // 0),
    compute: ($c[.] // 0),
    stream: ($s[.] // 0),
    total: ($t[.] // 0)
})
')

# ============================================================
# Monthly totals and cost calculation
# ============================================================
DPU_SUM=$(echo "$DAILY_TABLE" | jq '[.[].total] | add // 0')
READ_SUM=$(echo "$DAILY_TABLE" | jq '[.[].read] | add // 0')
WRITE_SUM=$(echo "$DAILY_TABLE" | jq '[.[].write] | add // 0')
COMPUTE_SUM=$(echo "$DAILY_TABLE" | jq '[.[].compute] | add // 0')
STREAM_SUM=$(echo "$DAILY_TABLE" | jq '[.[].stream] | add // 0')
NUM_DAYS=$(echo "$DAILY_TABLE" | jq 'length')

# Combined = TotalDPU + StreamDPU
TOTAL_WITH_STREAM=$(echo "$DPU_SUM + $STREAM_SUM" | bc)

# Billable = Combined - Free Tier (clamped to 0)
EXCESS_DPU=$(echo "$TOTAL_WITH_STREAM - $FREE_TIER_DPU" | bc)
if (( $(echo "$EXCESS_DPU < 0" | bc -l) )); then EXCESS_DPU=0; fi

# Cost = Billable DPU × price per 1M DPU
DPU_COST=$(echo "scale=4; $EXCESS_DPU * $DPU_PRICE / 1000000" | bc)

# ============================================================
# Daily breakdown table
# ============================================================
echo "  ┌────────────┬────────────┬────────────┬────────────┬────────────┬────────────┬──────────┐"
echo "  │    Date    │    Read    │   Write    │  Compute   │   Stream   │    Total   │   Cost   │"
echo "  ├────────────┼────────────┼────────────┼────────────┼────────────┼────────────┼──────────┤"

fmt_num() { printf "%'.0f" "$1"; }

echo "$DAILY_TABLE" | jq -r '.[] | [.date, .read, .write, .compute, .stream, .total] | @tsv' | \
while IFS=$'\t' read -r date read write compute stream total; do
    cost=$(echo "scale=2; $total * $DPU_PRICE / 1000000" | bc)
    printf "  │ %-10s │ %10s │ %10s │ %10s │ %10s │ %10s │ \$%6.2f │\n" \
        "$date" "$(fmt_num "$read")" "$(fmt_num "$write")" "$(fmt_num "$compute")" "$(fmt_num "$stream")" "$(fmt_num "$total")" "$cost"
done

echo "  ├────────────┼────────────┼────────────┼────────────┼────────────┼────────────┼──────────┤"
printf "  │ %-10s │ %10s │ %10s │ %10s │ %10s │ %10s │ \$%6.2f │\n" \
    "TOTAL" "$(fmt_num "$READ_SUM")" "$(fmt_num "$WRITE_SUM")" "$(fmt_num "$COMPUTE_SUM")" "$(fmt_num "$STREAM_SUM")" "$(fmt_num "$DPU_SUM")" "$DPU_COST"
echo "  └────────────┴────────────┴────────────┴────────────┴────────────┴────────────┴──────────┘"
echo ""

# ============================================================
# DPU composition bar chart
# ============================================================
BAR_WIDTH=40
echo "  DPU Composition:"
for label_var in "Read:$READ_SUM" "Write:$WRITE_SUM" "Compute:$COMPUTE_SUM" "Stream:$STREAM_SUM"; do
    label="${label_var%%:*}"
    val="${label_var##*:}"
    if (( $(echo "$DPU_SUM > 0" | bc -l) )); then
        pct=$(echo "scale=1; $val * 100 / $DPU_SUM" | bc)
        bar_len=$(echo "$val * $BAR_WIDTH / $DPU_SUM" | bc)
    else
        pct="0.0"
        bar_len=0
    fi
    bar_fill=$(printf '%*s' "$bar_len" '')
    printf '    %-8s %b%s%b %5s%%  (%s)\n' "$label" "$REV" "$bar_fill" "$RESET" "$pct" "$(fmt_num "$val")"
done
echo ""

# ============================================================
# Monthly summary box
# ============================================================
PEAK_DAY=$(echo "$DAILY_TABLE" | jq -r 'if length == 0 then "N/A" else (max_by(.total) | "\(.date) (\(.total | tostring | split(".")[0]) DPU)") end')

BOX_W=60
sum_line() {
    local content="  $1 $2"
    local pad=$((BOX_W - ${#content}))
    printf "  │%s%*s│\n" "$content" "$pad" ""
}
sum_empty() {
    printf "  │%*s│\n" "$BOX_W" ""
}

echo "  ┌$(printf '─%.0s' $(seq 1 $BOX_W))┐"
TITLE="Monthly Summary ($MONTH_LABEL)"
TITLE_PAD=$(( (BOX_W - ${#TITLE}) / 2 ))
printf "  │%*s%s%*s│\n" "$TITLE_PAD" "" "$TITLE" "$((BOX_W - TITLE_PAD - ${#TITLE}))" ""
echo "  ├$(printf '─%.0s' $(seq 1 $BOX_W))┤"
sum_line "Active Days:" "$NUM_DAYS"
sum_line "Peak Day:" "$PEAK_DAY"
sum_empty
sum_line "Total DPU (excl. Stream):" "$(fmt_num "$DPU_SUM")"
sum_line "Stream DPU (CDC):" "$(fmt_num "$STREAM_SUM")"
sum_line "Combined:" "$(fmt_num "$TOTAL_WITH_STREAM")"
sum_line "Free Tier:" "$(fmt_num "$FREE_TIER_DPU")"

if (( $(echo "$EXCESS_DPU > 0" | bc -l) )); then
    sum_line "Excess DPU:" "$(fmt_num "$EXCESS_DPU") (billable)"
else
    REMAINING=$(echo "$FREE_TIER_DPU - $TOTAL_WITH_STREAM" | bc)
    sum_line "Remaining:" "$(fmt_num "$REMAINING") DPU until limit"
fi

sum_empty
sum_line "★ Estimated DPU Cost:" "\$$(printf '%.2f' "$DPU_COST")"

# ============================================================
# Compare with Cost Explorer actual (if available)
# ============================================================
echo "  │                                                            │"
echo "  │  --- Cost Explorer Comparison ---                          │"

CE_COST=$(aws ce get-cost-and-usage \
    --granularity MONTHLY \
    --metrics UnblendedCost \
    --filter "{\"Dimensions\":{\"Key\":\"SERVICE\",\"Values\":[\"Aurora DSQL\"]}}" \
    --time-period Start="${MONTH_LABEL}-01",End="$(date -u +%Y-%m-01)" \
    --region us-east-1 \
    --output json 2>/dev/null | jq -r '.ResultsByTime[0].Total.UnblendedCost.Amount // "N/A"')

if [[ "$CE_COST" != "N/A" && "$CE_COST" != "0" ]]; then
    sum_line "Cost Explorer Actual:" "\$$(printf '%.2f' "$CE_COST")"
    DIFF=$(echo "scale=4; $DPU_COST - $CE_COST" | bc)
    sum_line "Difference:" "\$$(printf '%.2f' "$DIFF")"
else
    sum_line "Cost Explorer Actual:" "\$$(printf '%.2f' "${CE_COST:-0}")"
    sum_line "Note:" "Free Tier may fully cover usage"
fi

echo "  └$(printf '─%.0s' $(seq 1 $BOX_W))┘"
echo ""
