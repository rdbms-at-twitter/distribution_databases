#!/bin/bash
#
# fetch-dpus-cdc-v2.sh - Aurora DSQL DPU Cost Report (with CDC Stream support)
#
# Description:
#   Fetches CloudWatch metrics for an Aurora DSQL cluster and generates a
#   monthly DPU cost report including Read, Write, Compute, and Stream (CDC) DPUs.
#   Applies Free Tier deduction and calculates billable cost.
#
# Usage:
#   ./fetch-dpus-cdc-v2.sh <cluster-id> [region]
#
# Examples:
#   ./fetch-dpus-cdc-v2.sh lmabug6a7xcq              # us-east-1 (default)
#   ./fetch-dpus-cdc-v2.sh lmabug6a7xcq ap-northeast-1  # Tokyo
#
# Output:
#   - Daily DPU breakdown table (Read/Write/Compute/Stream)
#   - DPU composition bar chart
#   - Monthly summary with cost estimate (Free Tier applied)
#
# Notes:
#   - TotalDPU metric from CloudWatch does NOT include StreamDPU.
#     StreamDPU requires an additional "StreamId" dimension, so this script
#     fetches it separately via fetch_stream_metric().
#   - Cost = (TotalDPU + StreamDPU - FreeTier) × price_per_1M_DPU
#   - If no CDC stream exists, StreamDPU is reported as 0.
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
# Time range (current month)
# ============================================================
END_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
START_TIME=$(date -u +"%Y-%m-01T00:00:00Z")
MONTH_LABEL=$(date -u +"%Y-%m")
STORAGE_START_TIME=$(date -u +"%Y-%m-%dT%H:%M:%SZ" -d "1 hour ago" 2>/dev/null || date -u -v-1H +"%Y-%m-%dT%H:%M:%SZ")

# ============================================================
# Header (ANSI reverse video for title bar)
# ============================================================
ESC=$(printf '\033')
REV="${ESC}[7m"
RESET="${ESC}[0m"

echo ""
printf '  %b%s%b\n' "$REV" "                                                              " "$RESET"
printf '  %b%s%b\n' "$REV" "           Aurora DSQL — Monthly DPU Cost Report              " "$RESET"
printf '  %b%s%b\n' "$REV" "                                                              " "$RESET"
echo ""
echo "  Cluster:  $CLUSTER_ID"
echo "  Region:   $REGION"
echo "  Period:   $START_TIME → $END_TIME"
echo "  Pricing:  \$$DPU_PRICE/1M DPU  |  \$$STORAGE_PRICE/GB-month  |  Free: ${FREE_TIER_DPU} DPU + ${FREE_TIER_STORAGE_GB} GB"
echo ""

# ============================================================
# Storage size (latest data point from the past hour)
# ============================================================
STORAGE_SIZE_BYTES=$(aws cloudwatch get-metric-statistics \
    --namespace "AWS/AuroraDSQL" \
    --metric-name "ClusterStorageSize" \
    --dimensions Name=ClusterId,Value=$CLUSTER_ID \
    --start-time "$STORAGE_START_TIME" \
    --end-time "$END_TIME" \
    --period 60 \
    --statistics Average \
    --region "$REGION" \
    --output json | jq -r '.Datapoints | sort_by(.Timestamp) | last | .Average // "N/A"')

if [[ "$STORAGE_SIZE_BYTES" != "N/A" ]]; then
    STORAGE_SIZE_GB=$(echo "scale=6; $STORAGE_SIZE_BYTES / 1000000000" | bc)
    STORAGE_SIZE_DISPLAY=$(echo "$STORAGE_SIZE_BYTES" | awk '{
        if ($1 < 1000) printf "%.2f B", $1
        else if ($1 < 1000000) printf "%.2f KB", $1/1000
        else if ($1 < 1000000000) printf "%.2f MB", $1/1000000
        else printf "%.2f GB", $1/1000000000
    }')
else
    STORAGE_SIZE_GB="N/A"
    STORAGE_SIZE_DISPLAY="N/A"
fi

# ============================================================
# Metric fetching functions
# ============================================================

# fetch_metric - Fetch a standard DPU metric (Read/Write/Compute/Total)
# These metrics use only the ClusterId dimension.
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

# fetch_stream_metric - Fetch StreamDPU metric
# StreamDPU requires BOTH ClusterId and StreamId dimensions.
# CloudWatch returns empty Datapoints if only ClusterId is specified.
# This function auto-discovers the StreamId via dsql list-streams.
# Returns empty Datapoints JSON if no CDC stream exists.
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

# Fetch all metrics
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
DPU_SUM=$(echo "$DAILY_TABLE" | jq '[.[].total] | add // 0')       # TotalDPU (excludes Stream)
READ_SUM=$(echo "$DAILY_TABLE" | jq '[.[].read] | add // 0')
WRITE_SUM=$(echo "$DAILY_TABLE" | jq '[.[].write] | add // 0')
COMPUTE_SUM=$(echo "$DAILY_TABLE" | jq '[.[].compute] | add // 0')
STREAM_SUM=$(echo "$DAILY_TABLE" | jq '[.[].stream] | add // 0')   # StreamDPU (separate metric)
NUM_DAYS=$(echo "$DAILY_TABLE" | jq 'length')

# Combined = TotalDPU + StreamDPU (because CloudWatch TotalDPU does NOT include Stream)
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
fmt_cell() { printf "%10s" "$(fmt_num "$1")"; }

# Note: Daily "Cost" column shows raw cost without Free Tier deduction (reference only).
# The actual billable cost is in the Monthly Summary below.
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
# DPU composition bar chart (ANSI reverse video)
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
PEAK_DAY=$(echo "$DAILY_TABLE" | jq -r 'max_by(.total) | "\(.date) (\(.total | tostring | split(".")[0]) DPU)"')

# Helper: print a summary line within the box
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
TITLE="Monthly Summary"
TITLE_PAD=$(( (BOX_W - ${#TITLE}) / 2 ))
printf "  │%*s%s%*s│\n" "$TITLE_PAD" "" "$TITLE" "$((BOX_W - TITLE_PAD - ${#TITLE}))" ""
echo "  ├$(printf '─%.0s' $(seq 1 $BOX_W))┤"
sum_line "Storage:" "$STORAGE_SIZE_DISPLAY"
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
sum_line "DPU Cost:" "\$$(printf '%.2f' "$DPU_COST")"

if [[ "$STORAGE_SIZE_GB" != "N/A" ]]; then
    BILLABLE_STORAGE_GB=$(echo "scale=6; x=$STORAGE_SIZE_GB - $FREE_TIER_STORAGE_GB; if (x < 0) 0 else x" | bc)
    STORAGE_COST_MONTHLY=$(echo "scale=4; $BILLABLE_STORAGE_GB * $STORAGE_PRICE" | bc)
    sum_line "Storage Cost:" "\$$(printf '%.2f' "$STORAGE_COST_MONTHLY") ($(printf '%.2f' "$BILLABLE_STORAGE_GB") GB billable)"
    TOTAL_MONTHLY=$(echo "scale=2; $STORAGE_COST_MONTHLY + $DPU_COST" | bc)
    sum_empty
    sum_line "★ Total Cost:" "\$$(printf '%.2f' "$TOTAL_MONTHLY")"
else
    sum_line "Storage Cost:" "N/A"
fi

echo "  └$(printf '─%.0s' $(seq 1 $BOX_W))┘"
echo ""
