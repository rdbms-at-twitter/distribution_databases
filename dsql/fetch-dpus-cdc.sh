#!/bin/bash
#
# fetch-dpus-cdc.sh - Aurora DSQL DPU Cost Report
#
# Usage:
#   ./fetch-dpus-cdc.sh <cluster-id> [region] [--stream-id <stream-id>]
#
# Examples:
#   ./fetch-dpus-cdc.sh lmabug6a7xcqjqohrppfncdfaa                                    # us-east-1, no stream
#   ./fetch-dpus-cdc.sh lmabug6a7xcqjqohrppfncdfaa us-east-1 --stream-id artyuaev7bya  # with CDC stream
#   ./fetch-dpus-cdc.sh lmabug6a7xcqjqohrppfncdfaa ap-northeast-1                      # Tokyo
#
# Options:
#   --stream-id <id>   CDC stream identifier for StreamDPU metric (requires StreamId dimension)
#
# Output:
#   - Daily DPU breakdown table (Read/Write/Compute/Stream)
#   - Monthly summary with cost estimate
#   - Free tier usage tracking
#
# Pricing source: https://aws.amazon.com/aurora/dsql/pricing/
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
STREAM_ID=""

if [ $# -lt 1 ]; then
    echo "Usage: $0 <cluster-id> [region] [--stream-id <stream-id>]"
    echo ""
    echo "  Default region: $DEFAULT_REGION"
    echo "  Supported regions: ${!PRICING[*]}"
    exit 1
fi

CLUSTER_ID=$1
shift

# Parse remaining args
REGION="$DEFAULT_REGION"
while [ $# -gt 0 ]; do
    case "$1" in
        --stream-id)
            STREAM_ID="$2"
            shift 2
            ;;
        *)
            REGION="$1"
            shift
            ;;
    esac
done

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
# Header
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
# Storage
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

TOTAL_DPU_JSON=$(fetch_metric "TotalDPU")
READ_DPU_JSON=$(fetch_metric "ReadDPU")
WRITE_DPU_JSON=$(fetch_metric "WriteDPU")
COMPUTE_DPU_JSON=$(fetch_metric "ComputeDPU")

# StreamDPU requires both ClusterId and StreamId dimensions
if [[ -n "$STREAM_ID" ]]; then
    STREAM_DPU_JSON=$(aws cloudwatch get-metric-statistics \
        --namespace "AWS/AuroraDSQL" \
        --metric-name "StreamDPU" \
        --dimensions Name=ClusterId,Value=$CLUSTER_ID Name=StreamId,Value=$STREAM_ID \
        --start-time "$START_TIME" \
        --end-time "$END_TIME" \
        --period 86400 \
        --statistics Sum \
        --region "$REGION" \
        --output json)
else
    STREAM_DPU_JSON='{"Datapoints":[]}'
fi

# ============================================================
# Build daily table (merge by date)
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
# Monthly totals
# ============================================================
DPU_SUM=$(echo "$DAILY_TABLE" | jq '[.[].total] | add // 0')
READ_SUM=$(echo "$DAILY_TABLE" | jq '[.[].read] | add // 0')
WRITE_SUM=$(echo "$DAILY_TABLE" | jq '[.[].write] | add // 0')
COMPUTE_SUM=$(echo "$DAILY_TABLE" | jq '[.[].compute] | add // 0')
STREAM_SUM=$(echo "$DAILY_TABLE" | jq '[.[].stream] | add // 0')
NUM_DAYS=$(echo "$DAILY_TABLE" | jq 'length')

DPU_COST=$(echo "scale=4; $DPU_SUM * $DPU_PRICE / 1000000" | bc)

# ============================================================
# Daily breakdown table
# ============================================================
echo "  ┌────────────┬────────────┬────────────┬────────────┬────────────┬────────────┬──────────┐"
echo "  │    Date    │    Read    │   Write    │  Compute   │   Stream   │    Total   │   Cost   │"
echo "  ├────────────┼────────────┼────────────┼────────────┼────────────┼────────────┼──────────┤"

fmt_num() { printf "%'.0f" "$1"; }
fmt_cell() { printf "%10s" "$(fmt_num "$1")"; }

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
# DPU composition bar (using ANSI reverse video)
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
# Monthly summary
# ============================================================
PEAK_DAY=$(echo "$DAILY_TABLE" | jq -r 'max_by(.total) | "\(.date) (\(.total | tostring | split(".")[0]) DPU)"')
EXCESS_DPU=$(echo "$DPU_SUM - $FREE_TIER_DPU" | bc)

# Helper: print a summary line with right-aligned box border
# Usage: sum_line "Label:" "Value"
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
sum_line "Total DPU:" "$(fmt_num "$DPU_SUM")"
sum_line "Free Tier:" "$(fmt_num "$FREE_TIER_DPU")"

if (( $(echo "$EXCESS_DPU > 0" | bc -l) )); then
    EXCESS_COST=$(echo "scale=4; $EXCESS_DPU * $DPU_PRICE / 1000000" | bc)
    sum_line "Excess DPU:" "$(fmt_num "$EXCESS_DPU") (billable)"
else
    REMAINING=$(echo "0 - $EXCESS_DPU" | bc)
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
