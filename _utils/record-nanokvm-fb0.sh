#!/usr/bin/env bash

set -Eeuo pipefail

host="${NANOKVM_HOST:-root@192.168.2.10}"
fps="${FPS:-10}"
rotation="${ROTATE:-auto}"
output="${1:-nanokvm-fb0-$(date +%Y%m%d-%H%M%S).mp4}"

for command_name in ssh ffmpeg; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "缺少命令：$command_name" >&2
        exit 1
    fi
done

if [[ ! "$fps" =~ ^[1-9][0-9]*$ ]]; then
    echo "FPS 必须是正整数，当前值：$fps" >&2
    exit 1
fi

if [[ -e "$output" ]]; then
    echo "输出文件已存在，不会覆盖：$output" >&2
    exit 1
fi

fb_info=$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" \
    'printf "%s %s %s\n" "$(cat /sys/class/graphics/fb0/virtual_size)" "$(cat /sys/class/graphics/fb0/bits_per_pixel)" "$(cat /sys/class/graphics/fb0/stride)"')

read -r virtual_size bits_per_pixel stride <<<"$fb_info"
IFS=, read -r width height <<<"$virtual_size"

if [[ ! "$width" =~ ^[0-9]+$ || ! "$height" =~ ^[0-9]+$ || ! "$stride" =~ ^[0-9]+$ ]]; then
    echo "无法解析 fb0 参数：$fb_info" >&2
    exit 1
fi

if [[ "$bits_per_pixel" != "16" ]]; then
    echo "仅支持已验证的 16-bit RGB565 fb0，设备报告 ${bits_per_pixel} bpp" >&2
    exit 1
fi

expected_stride=$((width * 2))
if (( stride != expected_stride )); then
    echo "fb0 含行填充，暂不支持：stride=$stride，预期=$expected_stride" >&2
    exit 1
fi

frame_bytes=$((stride * height))
sleep_interval=$(awk -v fps="$fps" 'BEGIN { printf "%.6f", 1 / fps }')

case "$rotation" in
    auto)
        if (( height > width )); then
            video_filter="transpose=cclock,format=yuv420p"
            encoded_size="${height}x${width}"
        else
            video_filter="format=yuv420p"
            encoded_size="${width}x${height}"
        fi
        ;;
    none)
        video_filter="format=yuv420p"
        encoded_size="${width}x${height}"
        ;;
    clock|cclock)
        video_filter="transpose=${rotation},format=yuv420p"
        encoded_size="${height}x${width}"
        ;;
    *)
        echo "ROTATE 只支持 auto、none、clock 或 cclock" >&2
        exit 1
        ;;
esac

echo "设备：$host"
echo "fb0：${width}x${height}，RGB565LE，${fps} FPS"
echo "视频：$encoded_size -> $output"
echo "按 Ctrl-C 结束并保存。"

set +e
ssh -o BatchMode=yes "$host" \
    "while :; do dd if=/dev/fb0 bs=$frame_bytes count=1 2>/dev/null || exit; sleep $sleep_interval; done" |
    ffmpeg -hide_banner -loglevel warning \
        -f rawvideo -pixel_format rgb565le -video_size "${width}x${height}" \
        -framerate "$fps" -i pipe:0 -an \
        -vf "$video_filter" -c:v libx264 -preset veryfast -crf 18 \
        -movflags +faststart "$output"
pipeline_status=("${PIPESTATUS[@]}")
set -e

if [[ -s "$output" ]]; then
    echo
    echo "已保存：$(realpath "$output")"
    exit 0
fi

echo "录制失败，未生成有效视频（ssh=${pipeline_status[0]}，ffmpeg=${pipeline_status[1]}）" >&2
exit 1
