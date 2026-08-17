#!/usr/bin/env bash
set -euo pipefail

VIDEO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${VIDEO_DIR}/.voiced-render"
SOURCE_DIR="${VIDEO_DIR}/recordings"
FONT_BOLD="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

mkdir -p "${WORK_DIR}"

clean_audio() {
  local source="$1" start="$2" end="$3" duration="$4" output="$5"
  ffmpeg -y -i "${source}" \
    -af "atrim=start=${start}:end=${end},asetpts=PTS-STARTPTS,pan=mono|c0=c0,highpass=f=105,lowpass=f=11000,equalizer=f=240:t=q:w=0.9:g=-4,agate=threshold=0.028:ratio=4:range=0.12:attack=6:release=85:knee=3,afftdn=nr=5:nf=-50:tn=1,loudnorm=I=-18:TP=-2:LRA=7,afade=t=in:st=0:d=0.04,afade=t=out:st=$(awk -v d="${end}" -v s="${start}" 'BEGIN {printf "%.3f", d-s-0.07}'):d=0.06,adelay=200,apad" \
    -t "${duration}" -ar 48000 -ac 1 -c:a pcm_s16le "${output}"
}

loop_scene() {
  local source="$1" duration="$2" output="$3"
  ffmpeg -y -stream_loop -1 -i "${source}" -t "${duration}" \
    -an -c:v libx264 -pix_fmt yuv420p -r 30 "${output}"
}

clean_audio "${SOURCE_DIR}/01-intro.webm"        0.713  7.801  7.738  "${WORK_DIR}/01.wav"
clean_audio "${SOURCE_DIR}/02-mechanism.webm"    0.602 15.054 15.102  "${WORK_DIR}/02.wav"
clean_audio "${SOURCE_DIR}/03-target-intel.webm" 1.172 10.024  9.502  "${WORK_DIR}/03.wav"
clean_audio "${SOURCE_DIR}/04-live-update.webm"  1.182 11.123 10.591  "${WORK_DIR}/04.wav"
clean_audio "${SOURCE_DIR}/05-study-scope.webm"  0.943 14.549 14.256  "${WORK_DIR}/05.wav"
clean_audio "${SOURCE_DIR}/06-result.webm"       1.304 15.776 15.122  "${WORK_DIR}/06.wav"
clean_audio "${SOURCE_DIR}/07-offer.webm"        1.617 12.461 11.494  "${WORK_DIR}/07.wav"

loop_scene "${VIDEO_DIR}/.render/01-intro.mp4"   7.738  "${WORK_DIR}/01.mp4"
loop_scene "${VIDEO_DIR}/.render/02-landing.mp4" 15.102 "${WORK_DIR}/02.mp4"
loop_scene "${VIDEO_DIR}/.render/03-start.mp4"   9.502  "${WORK_DIR}/03.mp4"

loop_scene "${VIDEO_DIR}/.render/04-one-pick.mp4" 5.296 "${WORK_DIR}/04a.mp4"
loop_scene "${VIDEO_DIR}/.render/05-live.mp4"     5.295 "${WORK_DIR}/04b.mp4"
printf "file '%s'\nfile '%s'\n" "${WORK_DIR}/04a.mp4" "${WORK_DIR}/04b.mp4" > "${WORK_DIR}/04.ffconcat"
ffmpeg -y -f concat -safe 0 -i "${WORK_DIR}/04.ffconcat" -an -c copy "${WORK_DIR}/04.mp4"

ffmpeg -y -f lavfi -i "color=c=0x05090c:s=1920x1080:d=14.256:r=30" \
  -vf "drawtext=fontfile=${FONT_REGULAR}:text='WHAT THE STUDY ISOLATED':fontcolor=0x9fb0ba:fontsize=34:x=(w-text_w)/2:y=205,drawtext=fontfile=${FONT_BOLD}:text='DRAFT QUALITY ONLY':fontcolor=0x00ef7b:fontsize=92:x=(w-text_w)/2:y=330,drawtext=fontfile=${FONT_BOLD}:text='WEEK 1 LINEUP FROZEN':fontcolor=white:fontsize=49:x=(w-text_w)/2:y=490,drawtext=fontfile=${FONT_REGULAR}:text='NO WAIVERS  |  NO TRADES  |  NO START/SIT CHANGES':fontcolor=0x9fb0ba:fontsize=32:x=(w-text_w)/2:y=610,drawtext=fontfile=${FONT_REGULAR}:text='Designed to isolate the quality of the draft itself.':fontcolor=0x7f929e:fontsize=29:x=(w-text_w)/2:y=735" \
  -an -c:v libx264 -pix_fmt yuv420p -r 30 "${WORK_DIR}/05.mp4"

loop_scene "${VIDEO_DIR}/.render/06-evidence.mp4" 15.122 "${WORK_DIR}/06.mp4"
loop_scene "${VIDEO_DIR}/.render/07-cta.mp4"      11.494 "${WORK_DIR}/07.mp4"

printf "file '%s'\nfile '%s'\nfile '%s'\nfile '%s'\nfile '%s'\nfile '%s'\nfile '%s'\n" \
  "${WORK_DIR}/01.mp4" "${WORK_DIR}/02.mp4" "${WORK_DIR}/03.mp4" "${WORK_DIR}/04.mp4" \
  "${WORK_DIR}/05.mp4" "${WORK_DIR}/06.mp4" "${WORK_DIR}/07.mp4" > "${WORK_DIR}/video.ffconcat"

printf "file '%s'\nfile '%s'\nfile '%s'\nfile '%s'\nfile '%s'\nfile '%s'\nfile '%s'\n" \
  "${WORK_DIR}/01.wav" "${WORK_DIR}/02.wav" "${WORK_DIR}/03.wav" "${WORK_DIR}/04.wav" \
  "${WORK_DIR}/05.wav" "${WORK_DIR}/06.wav" "${WORK_DIR}/07.wav" > "${WORK_DIR}/audio.ffconcat"

ffmpeg -y -f concat -safe 0 -i "${WORK_DIR}/video.ffconcat" -an -c copy "${WORK_DIR}/video.mp4"
ffmpeg -y -f concat -safe 0 -i "${WORK_DIR}/audio.ffconcat" -c:a aac -b:a 192k "${WORK_DIR}/voice.m4a"
ffmpeg -y -i "${WORK_DIR}/video.mp4" -i "${WORK_DIR}/voice.m4a" \
  -map 0:v:0 -map 1:a:0 -c:v copy -c:a copy -shortest -movflags +faststart \
  "${VIDEO_DIR}/overadp-adp-vs-model-voiced.mp4"

ffmpeg -y -i "${VIDEO_DIR}/overadp-adp-vs-model-voiced.mp4" \
  -vf "subtitles=${VIDEO_DIR}/overadp-voiced.srt:force_style='FontName=DejaVu Sans,FontSize=19,PrimaryColour=&H00FFFFFF,OutlineColour=&H00101820,BorderStyle=1,Outline=2,Shadow=0,MarginV=48,Alignment=2'" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -c:a copy -movflags +faststart \
  "${VIDEO_DIR}/overadp-adp-vs-model-final.mp4"

ffprobe -v error -show_entries format=duration,size -of default=noprint_wrappers=1 \
  "${VIDEO_DIR}/overadp-adp-vs-model-final.mp4"
