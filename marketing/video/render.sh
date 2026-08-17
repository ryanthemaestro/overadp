#!/usr/bin/env bash
set -euo pipefail

VIDEO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="${VIDEO_DIR}/.render"
PICTURES_DIR="/home/nar/Pictures"
FONT_BOLD="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

mkdir -p "${WORK_DIR}"

ffmpeg -y -f lavfi -i "color=c=0x05090c:s=1920x1080:d=6:r=30" \
  -vf "drawtext=fontfile=${FONT_BOLD}:text='ADP TELLS YOU THE ROOM.':fontcolor=white:fontsize=76:x=(w-text_w)/2:y=382,drawtext=fontfile=${FONT_BOLD}:text='OVERADP TELLS YOU WHO TO DRAFT NOW.':fontcolor=0x00ef7b:fontsize=58:x=(w-text_w)/2:y=500,drawtext=fontfile=${FONT_REGULAR}:text='ROSTER-AWARE FANTASY DRAFTING':fontcolor=0x9fb0ba:fontsize=28:x=(w-text_w)/2:y=628" \
  -c:v libx264 -pix_fmt yuv420p -r 30 "${WORK_DIR}/01-intro.mp4"

ffmpeg -y -loop 1 -t 9 -i "${PICTURES_DIR}/Screenshot from 2026-08-16 11-47-53.png" \
  -vf "crop=3730:1530:105:373,scale=1920:-2,pad=1920:1080:0:(oh-ih)/2:0x05090c,drawbox=x=0:y=0:w=iw:h=108:color=0x05090c@0.94:t=fill,drawtext=fontfile=${FONT_BOLD}:text='A DRAFT ASSISTANT THAT REACTS TO YOUR ROSTER':fontcolor=white:fontsize=39:x=70:y=32" \
  -c:v libx264 -pix_fmt yuv420p -r 30 "${WORK_DIR}/02-landing.mp4"

ffmpeg -y -loop 1 -t 11 -i "${PICTURES_DIR}/Screenshot from 2026-08-04 19-04-08.png" \
  -vf "crop=3635:1510:205:373,scale=1920:-2,pad=1920:1080:0:(oh-ih)/2:0x05090c,drawbox=x=0:y=0:w=iw:h=104:color=0x05090c@0.94:t=fill,drawtext=fontfile=${FONT_BOLD}:text='PICK 1  |  TARGET INTEL STARTS WITH THE BEST AVAILABLE FIT':fontcolor=0x00ef7b:fontsize=36:x=62:y=31" \
  -c:v libx264 -pix_fmt yuv420p -r 30 "${WORK_DIR}/03-start.mp4"

ffmpeg -y -loop 1 -t 11 -i "${PICTURES_DIR}/Screenshot from 2026-08-05 12-57-00.png" \
  -vf "crop=1817:689:103:351,scale=1920:-2,pad=1920:1080:0:(oh-ih)/2:0x05090c,drawbox=x=0:y=0:w=iw:h=104:color=0x05090c@0.94:t=fill,drawtext=fontfile=${FONT_BOLD}:text='AFTER ONE PICK  |  THE RECOMMENDATION CHANGES':fontcolor=0x00ef7b:fontsize=39:x=62:y=29" \
  -c:v libx264 -pix_fmt yuv420p -r 30 "${WORK_DIR}/04-one-pick.mp4"

ffmpeg -y -loop 1 -t 11 -i "${PICTURES_DIR}/Screenshot from 2026-08-05 13-05-44.png" \
  -vf "crop=1817:689:103:351,scale=1920:-2,pad=1920:1080:0:(oh-ih)/2:0x05090c,drawbox=x=0:y=0:w=iw:h=104:color=0x05090c@0.94:t=fill,drawtext=fontfile=${FONT_BOLD}:text='PICK 72  |  ROSTER NEED + SCARCITY + NEXT-TURN AVAILABILITY':fontcolor=0x00ef7b:fontsize=34:x=62:y=31" \
  -c:v libx264 -pix_fmt yuv420p -r 30 "${WORK_DIR}/05-live.mp4"

ffmpeg -y -f lavfi -i "color=c=0x05090c:s=1920x1080:d=10:r=30" \
  -vf "drawtext=fontfile=${FONT_REGULAR}:text='1,000 PAIRED HISTORICAL DRAFTS  |  2023-2024':fontcolor=0x9fb0ba:fontsize=31:x=(w-text_w)/2:y=178,drawtext=fontfile=${FONT_BOLD}:text='50.6%':expansion=none:fontcolor=0x00ef7b:fontsize=132:x=325:y=345,drawtext=fontfile=${FONT_BOLD}:text='25.7%':expansion=none:fontcolor=white:fontsize=132:x=1180:y=345,drawtext=fontfile=${FONT_BOLD}:text='TARGET INTEL':fontcolor=0x00ef7b:fontsize=36:x=360:y=515,drawtext=fontfile=${FONT_BOLD}:text='ADP FIRST':fontcolor=white:fontsize=36:x=1245:y=515,drawtext=fontfile=${FONT_REGULAR}:text='TOP-THREE REGULAR-SEASON RATE  |  WEEK-1 LINEUP FROZEN':fontcolor=0x9fb0ba:fontsize=31:x=(w-text_w)/2:y=666,drawtext=fontfile=${FONT_REGULAR}:text='Retrospective exploratory simulation. Championship rate did not improve.':fontcolor=0x7f929e:fontsize=27:x=(w-text_w)/2:y=821" \
  -c:v libx264 -pix_fmt yuv420p -r 30 "${WORK_DIR}/06-evidence.mp4"

ffmpeg -y -f lavfi -i "color=c=0x05090c:s=1920x1080:d=8:r=30" \
  -vf "drawtext=fontfile=${FONT_BOLD}:text='TRY 5 ROSTER-AWARE PICKS FREE':fontcolor=0x00ef7b:fontsize=72:x=(w-text_w)/2:y=375,drawtext=fontfile=${FONT_BOLD}:text='OVERADP.COM':fontcolor=white:fontsize=88:x=(w-text_w)/2:y=505,drawtext=fontfile=${FONT_REGULAR}:text='Historical evidence is not a guarantee of future results.':fontcolor=0x7f929e:fontsize=27:x=(w-text_w)/2:y=683" \
  -c:v libx264 -pix_fmt yuv420p -r 30 "${WORK_DIR}/07-cta.mp4"

ffmpeg -y -f concat -safe 0 -i "${VIDEO_DIR}/scenes.ffconcat" -c copy "${VIDEO_DIR}/overadp-adp-vs-model-voiceover.mp4"

ffprobe -v error -show_entries format=duration,size -of default=noprint_wrappers=1 "${VIDEO_DIR}/overadp-adp-vs-model-voiceover.mp4"
