# Composes the demo video from the frames of capture_video.py: VIDEO/manifest.json -> VIDEO/klayout_em_export_demo.mp4
# (H.264, 30 fps), plus .srt subtitles, YouTube chapter list and a timed narration script (for a voice-over later).
# Run in a Python with Pillow and imageio-ffmpeg (e.g. d:\venv\palace):
#   python doc/video/compose_video.py [VIDEO folder] [--scale 2]      (--scale 2: 3840x2160 from the same grabs)
# Every shot lasts as long as its caption needs to be read, plus its moves (zoom frames, pointer clicks) and hold.
import argparse
import json
import os
import textwrap

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

FPS = 30
W, H = 1920, 1080
FADE = 0.3                          # crossfade between shots (s)
MOVE_FPS = 20                       # KLayout zoom frames per second
POINTER_MOVE, CLICK, PAUSE = 0.7, 0.35, 0.35
CAPTION_BAND = 150                  # caption band at the bottom (logical px)
BACKGROUND = (30, 32, 36)
FONTS = r"C:\Windows\Fonts"


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def ease(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def reading_time(caption):
    return max(3.0, 1.5 + 0.055 * len(caption)) if caption else 0.0


class Composer:
    def __init__(self, video, scale):
        self.video, self.s = video, scale
        with open(os.path.join(video, "manifest.json")) as f:
            self.manifest = json.load(f)
        self.z = self.manifest.get("zoom", 1.0)        # KLayout's logical pixels -> video pixels
        self.lw = round(self.manifest["layout_w"] * self.z)
        self.cache = {}
        self.sans = font("segoeui.ttf", 34 * scale)
        self.sans_bold = font("segoeuib.ttf", 30 * scale)
        self.pointer_pos = (W * 0.5, H * 0.5)

    # ---------- pieces ----------
    def image(self, part, size=None):
        """A grab at its logical size (times scale), or at size."""
        path = os.path.join(self.video, part["file"])
        size = size or (round(part["w"] * self.z * self.s), round(part["h"] * self.z * self.s))
        key = (path, size)
        if key not in self.cache:
            if not os.path.isfile(path):
                print("missing", path)
                self.cache[key] = Image.new("RGB", size, (90, 0, 0))
            else:
                self.cache[key] = Image.open(path).convert("RGB").resize(size, Image.LANCZOS)
        return self.cache[key]

    def fitted(self, path, box_w, box_h):
        path = os.path.join(self.video, path)
        key = (path, "fit", box_w, box_h)
        if key not in self.cache:
            im = Image.open(path).convert("RGB")
            f = min(box_w / im.width, box_h / im.height)
            self.cache[key] = im.resize((round(im.width * f), round(im.height * f)), Image.LANCZOS)
        return self.cache[key]

    def dialog_pos(self, dialog):
        if "x" in dialog:
            return dialog["x"] * self.z, dialog["y"] * self.z
        return (self.lw - dialog["w"] * self.z) / 2, (H - CAPTION_BAND - dialog["h"] * self.z) / 2 + 40

    def shadowed(self, frame, im, x, y):
        s = self.s
        shadow = Image.new("RGBA", (im.width + 24 * s, im.height + 24 * s), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle((12 * s, 12 * s, im.width + 12 * s, im.height + 12 * s),
                                                 8 * s, fill=(0, 0, 0, 110))
        frame.paste(shadow, (round(x * s) - 4 * s, round(y * s) - 2 * s), shadow)
        frame.paste(im, (round(x * s), round(y * s)))

    def caption_overlay(self, text):
        s = self.s
        overlay = Image.new("RGBA", (W * s, H * s), (0, 0, 0, 0))
        if not text:
            return overlay
        draw = ImageDraw.Draw(overlay)
        lines = textwrap.wrap(text, 92)
        line_h = 46 * s
        top = H * s - 40 * s - line_h * len(lines) - 24 * s
        draw.rounded_rectangle((60 * s, top, W * s - 60 * s, H * s - 30 * s), 14 * s, fill=(15, 18, 24, 215))
        for i, line in enumerate(lines):
            draw.text((W * s / 2, top + 22 * s + i * line_h), line, font=self.sans, fill=(245, 245, 245),
                      anchor="ma")
        return overlay

    def chapter_overlay(self, overlay, chapter):
        if not chapter:
            return
        s = self.s
        draw = ImageDraw.Draw(overlay)
        width = draw.textlength(chapter, font=self.sans_bold) + 40 * s
        x, y = W * s - width - 30 * s, H * s - 30 * s - 3 * 46 * s - 70 * s
        draw.rounded_rectangle((x, y, x + width, y + 52 * s), 26 * s, fill=(37, 99, 235, 235))
        draw.text((x + width / 2, y + 26 * s), chapter, font=self.sans_bold, fill="white", anchor="mm")

    def pointer(self, frame, x, y, click):
        s = self.s
        draw = ImageDraw.Draw(frame, "RGBA")
        if click is not None:              # ripple, 0..1
            r = (10 + 30 * click) * s
            draw.ellipse((x * s - r, y * s - r, x * s + r, y * s + r), outline=(255, 200, 0, round(255 * (1 - click))),
                         width=4 * s)
        arrow = [(0, 0), (0, 26), (6.5, 20), (11, 30), (15, 28), (10.5, 18.5), (19, 18.5)]
        points = [((x + px * 1.1) * s, (y + py * 1.1) * s) for px, py in arrow]
        draw.polygon(points, fill=(255, 255, 255), outline=(0, 0, 0))
        draw.line(points + [points[0]], fill=(0, 0, 0), width=2 * s)

    # ---------- full-frame shots ----------
    def card(self, card):
        s = self.s
        im = Image.new("RGB", (W * s, H * s), BACKGROUND)
        draw = ImageDraw.Draw(im)
        for y in range(H * s):              # soft vertical gradient
            c = round(18 + 28 * y / (H * s))
            draw.line((0, y, W * s, y), fill=(c, c + 6, c + 22))
        draw.rectangle((0, 0, 14 * s, H * s), fill=(37, 99, 235))
        draw.text((160 * s, 330 * s), card["title"], font=font("segoeuib.ttf", 84 * s), fill="white")
        for i, line in enumerate(card.get("lines", [])):
            draw.text((164 * s, (480 + 66 * i) * s), line, font=font("segoeui.ttf", 40 * s),
                      fill=(205, 215, 235) if i else (255, 255, 255))
        return im

    def picture(self, image):
        s = self.s
        im = Image.new("RGB", (W * s, H * s), (236, 238, 242))
        pic = self.fitted(image["file"], (W - 120) * s, (H - CAPTION_BAND - 60) * s)
        im.paste(pic, ((W * s - pic.width) // 2, (30 * s + (H - CAPTION_BAND - 60) * s - pic.height) // 2))
        return im

    def text_lines(self, text):
        """(image of the text page, its scroll range in px)."""
        s = self.s
        title_font = font("segoeuib.ttf", 40 * s)
        mono = text.get("mono", False)
        small = mono and len(text["lines"]) > 12          # a netlist: small; a file list: large
        body = font("consola.ttf" if mono else "segoeui.ttf", (21 if small else 32) * s)
        line_h = (29 if small else 50) * s
        width = (W - 160) * s
        page = Image.new("RGB", (W * s, max(H * s, 200 * s + line_h * len(text["lines"]) + CAPTION_BAND * s)),
                         (24, 26, 30))
        draw = ImageDraw.Draw(page)
        draw.text((80 * s, 60 * s), text["title"], font=title_font, fill="white")
        for i, line in enumerate(text["lines"]):
            while line and draw.textlength(line, font=body) > width:
                line = line[:-2] + "\u2026"
            color = (230, 230, 230)
            if mono:
                if line.startswith("*"):
                    color = (130, 160, 130)
                elif line.startswith("."):
                    color = (110, 190, 255)
                elif line[:1] in "XR":
                    color = (255, 210, 120)
            draw.text((80 * s, 150 * s + i * line_h), line, font=body, fill=color)
        return page, max(0, page.height - H * s)

    # ---------- the video ----------
    def plan(self):
        """Per shot: its timing (start, duration, segments)."""
        t = 0.0
        plans = []
        for shot in self.manifest["shots"]:
            moves = shot.get("layout") if isinstance(shot.get("layout"), list) else None
            move_time = len(moves) / MOVE_FPS if moves else 0.0
            pointer_time = len(shot.get("pointer", [])) * (POINTER_MOVE + CLICK + PAUSE)
            duration = max(reading_time(shot["caption"]), move_time + pointer_time + 1.2) + shot.get("hold", 0)
            plans.append((t, duration, move_time))
            t += duration
        return plans

    def resolve(self, target, dialog, panel_scroll):
        x, y = target["x"] * self.z, target["y"] * self.z
        if target["in"] == "layout":
            return x, y
        if target["in"] == "panel":
            return self.lw + x, y - panel_scroll
        dx, dy = self.dialog_pos(dialog) if dialog else (0, 0)
        return dx + x, dy + y

    def frames(self, shot, duration, move_time):
        s = self.s
        static = None
        scroll_max = 0
        if "card" in shot:
            static = self.card(shot["card"])
        elif "image" in shot:
            static = self.picture(shot["image"])
        elif "text" in shot:
            page, scroll_max = self.text_lines(shot["text"])
        overlay = self.caption_overlay(shot["caption"])
        self.chapter_overlay(overlay, self.current_chapter)
        layout = shot.get("layout")
        moves = layout if isinstance(layout, list) else None
        panel = shot.get("panel")
        panel_im = self.image(panel) if panel else None
        panel_scroll_max = max(0, round(panel["h"] * self.z) - H) if panel else 0
        dialog = shot.get("dialog")
        dialog_im = self.image(dialog) if dialog else None
        popup = shot.get("popup")
        targets = shot.get("pointer", [])
        n = round(duration * FPS)
        start_pointer = self.pointer_pos
        for i in range(n):
            t = i / FPS
            if static is not None:
                frame = static.copy()
            elif "text" in shot:
                y = round(scroll_max * ease((t - 2.0) / max(1.0, duration - 4.0)))
                frame = page.crop((0, y, W * s, y + H * s))
            else:
                frame = Image.new("RGB", (W * s, H * s), BACKGROUND)
                if moves:
                    k = min(len(moves) - 1, int(t * MOVE_FPS))
                    frame.paste(self.image(moves[k]), (0, 0))
                elif layout:
                    frame.paste(self.image(layout), (0, 0))
                scroll = 0
                if panel_im is not None:
                    scroll = round(panel_scroll_max * ease((t - move_time - 1.5) / max(1.0, duration - 3.0)))
                    frame.paste(panel_im.crop((0, scroll * s, panel_im.width, scroll * s + H * s)),
                                (self.lw * s, 0))
                    ImageDraw.Draw(frame).line((self.lw * s, 0, self.lw * s, H * s), fill=(0, 0, 0),
                                               width=2 * s)
                if dialog_im is not None:
                    x, y = self.dialog_pos(dialog)
                    self.shadowed(frame, dialog_im, x, y)
                    if popup:
                        px, py = self.resolve(popup["below"], dialog, 0)
                        self.shadowed(frame, self.image(popup), px - 60, py + 16)
            # pointer: glide to each target, click, pause
            if targets:
                step = POINTER_MOVE + CLICK + PAUSE
                k = min(len(targets) - 1, int(max(0.0, t - move_time) / step))
                local = max(0.0, t - move_time) - k * step
                end = self.resolve(targets[k], dialog, scroll if static is None and "text" not in shot else 0)
                begin = start_pointer if k == 0 else self.resolve(targets[k - 1], dialog, 0)
                f = ease(local / POINTER_MOVE)
                x, y = begin[0] + (end[0] - begin[0]) * f, begin[1] + (end[1] - begin[1]) * f
                click = (local - POINTER_MOVE) / CLICK if POINTER_MOVE <= local < POINTER_MOVE + CLICK else None
                self.pointer(frame, x, y, click)
                self.pointer_pos = (x, y)
            frame.paste(overlay, (0, 0), overlay)
            yield frame

    def render(self, output):
        plans = self.plan()
        writer = imageio_ffmpeg.write_frames(output, (W * self.s, H * self.s), fps=FPS, codec="libx264",
                                             quality=None, macro_block_size=8,
                                             output_params=["-crf", "18", "-preset", "medium"])
        writer.send(None)
        previous = None
        self.current_chapter = None
        for index, (shot, (start, duration, move_time)) in enumerate(zip(self.manifest["shots"], plans)):
            if shot.get("chapter"):
                self.current_chapter = shot["chapter"]
            if "card" in shot:
                self.current_chapter = None
            print(f"{start:6.1f} s  shot {index + 1:2d}  {shot['caption'][:70]}", flush=True)
            for i, frame in enumerate(self.frames(shot, duration, move_time)):
                if previous is not None and i < FADE * FPS:
                    frame = Image.blend(previous, frame, (i + 1) / (FADE * FPS + 1))
                writer.send(frame.tobytes())
                last = frame
            previous = last
        writer.close()
        return plans


def stamp(t, srt=False):
    h, rest = divmod(t, 3600)
    m, sec = divmod(rest, 60)
    if srt:
        return f"{int(h):02d}:{int(m):02d}:{int(sec):02d},{round((sec % 1) * 1000):03d}"
    return f"{int(m)}:{int(sec):02d}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", nargs="?", default=r"D:\Palace_testcases\klayout_export\video")
    parser.add_argument("--scale", type=int, default=1, help="1: 1920x1080, 2: 3840x2160")
    args = parser.parse_args()
    composer = Composer(args.video, args.scale)
    output = os.path.join(args.video, "klayout_em_export_demo.mp4" if args.scale == 1 else
                          f"klayout_em_export_demo_{args.scale}x.mp4")
    plans = composer.render(output)
    shots = composer.manifest["shots"]
    total = plans[-1][0] + plans[-1][1]
    with open(os.path.join(args.video, "klayout_em_export_demo.srt"), "w", encoding="utf-8") as f:
        n = 0
        for shot, (start, duration, _) in zip(shots, plans):
            if shot["caption"]:
                n += 1
                f.write(f"{n}\n{stamp(start, True)} --> {stamp(start + duration, True)}\n{shot['caption']}\n\n")
    with open(os.path.join(args.video, "youtube_chapters.txt"), "w", encoding="utf-8") as f:
        for shot, (start, _, _) in zip(shots, plans):      # YouTube: the first at 0:00, each at least 10 s
            if shot.get("chapter"):
                f.write(f"{stamp(start)} {shot['chapter']}\n")
    with open(os.path.join(args.video, "narration.md"), "w", encoding="utf-8") as f:
        f.write(f"# Narration script ({stamp(total)})\n\n")
        for shot, (start, duration, _) in zip(shots, plans):
            text = shot["caption"] or " / ".join([shot.get("card", {}).get("title", "")] +
                                                 shot.get("card", {}).get("lines", []))
            f.write(f"- **{stamp(start)}** ({duration:.0f} s){' [' + shot['chapter'] + ']' if shot.get('chapter') else ''}"
                    f" {text}\n")
    print(f"wrote {output}: {stamp(total)} ({total:.0f} s)")


if __name__ == "__main__":
    main()
