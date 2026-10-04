# -*- coding: utf-8 -*-
# Превращает запись экрана Corebound в обучающие данные.
#
# На выходе два файла и оба маленькие:
#   взгляд_<имя>.mp4  — то, что будет видеть бот: 208x92, 4 кадра в секунду
#   руль_<имя>.csv    — куда вёл палец в каждом кадре
#
# Сама запись не хранится: её скачивают во временную папку, разбирают
# и удаляют. Заход на три минуты весит 86 МБ, разметка из него — меньше
# мегабайта.
#
# Как читается джойстик. Три подхода провалились, прежде чем вышло:
# искать яркое — ловится белый шарик из игры; искать круглое — ловится
# само кольцо; и хуже всего было резать кадры в оттенки серого, потому
# что этим выбрасывается главный признак. Работает вот что:
#   1. интерфейс БЕСЦВЕТНЫЙ, а игра цветная — отделяем по насыщенности;
#   2. внешнее кольцо НЕПОДВИЖНО — находим его по тому, что держится во
#      многих кадрах, и дальше смотрим только внутрь него;
#   3. рычажок — это подвижная часть интерфейса внутри кольца.
import subprocess, sys, os, glob, shutil
import numpy as np
from PIL import Image, ImageDraw

FPS   = 4            # кадров в секунду в разметке
VIEW  = (208, 92)    # размер взгляда бота
FFMPEG = os.path.expanduser("~/.local/bin/ffmpeg")


def прогнать(*args):
    subprocess.run([FFMPEG, "-v", "error", "-y", *args], check=True)


def разобрать(видео, имя, куда):
    tmp = "/tmp/разметка_кадры"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)

    # 1. Вырезка под джойстик — в цвете, иначе признак теряется
    прогнать("-i", видео, "-vf",
             f"fps={FPS},crop=in_w*0.26:in_h*0.42:0:in_h*0.58,scale=iw/2:ih/2",
             f"{tmp}/%05d.png")
    fs = sorted(glob.glob(f"{tmp}/*.png"))
    A = np.stack([np.asarray(Image.open(f).convert("RGB"), np.float32) for f in fs])
    N, H, W, _ = A.shape

    mx = A.max(3); mn = A.min(3)
    sat = (mx - mn) / np.maximum(mx, 1)
    UI = ((mx > 90) & (sat < 0.17)).astype(np.float32)

    # 2. Неподвижное кольцо
    perm = UI.mean(0)
    порог = max(0.25, perm.max() * 0.6)
    ys, xs = np.nonzero(perm > порог)
    if len(xs) < 100:
        print("  кольцо джойстика не найдено — запись не годится")
        return None
    cx, cy = xs.mean(), ys.mean()
    rad = np.percentile(np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2), 97)

    # 3. Подвижная часть внутри кольца
    Y, X = np.mgrid[0:H, 0:W]
    внутри = ((X - cx) ** 2 + (Y - cy) ** 2) <= (rad * 1.05) ** 2
    строки, найдено = [], 0
    for i in range(N):
        m = (UI[i] > 0) & внутри & (perm < порог * 0.8)
        if m.sum() >= 25:
            dx = (X[m].mean() - cx) / rad
            dy = (Y[m].mean() - cy) / rad
            строки.append((i, round(float(dx), 4), round(float(dy), 4), 1))
            найдено += 1
        else:
            строки.append((i, 0.0, 0.0, 0))      # 0 = не прочитано
    доля = 100 * найдено / N

    руль = os.path.join(куда, f"руль_{имя}.csv")
    with open(руль, "w", encoding="utf-8") as f:
        f.write("кадр,вбок,ввысь,прочитано\n")
        for r in строки:
            f.write("%d,%.4f,%.4f,%d\n" % r)

    # 4. Взгляд бота
    взгляд = os.path.join(куда, f"взгляд_{имя}.mp4")
    прогнать("-i", видео, "-vf", f"fps={FPS},scale={VIEW[0]}:{VIEW[1]}",
             "-an", "-c:v", "libx264", "-crf", "28", "-preset", "veryfast", взгляд)

    shutil.rmtree(tmp, ignore_errors=True)
    return dict(кадров=N, прочитано=найдено, доля=доля,
                кольцо=(round(cx, 1), round(cy, 1), round(rad, 1)),
                взгляд=взгляд, руль=руль)


if __name__ == "__main__":
    видео, имя = sys.argv[1], sys.argv[2]
    куда = sys.argv[3] if len(sys.argv) > 3 else "/home/user/corebound/данные"
    os.makedirs(куда, exist_ok=True)
    r = разобрать(видео, имя, куда)
    if r:
        print(f"кадров: {r['кадров']}, джойстик прочитан в {r['прочитано']} "
              f"({r['доля']:.0f}%)")
        print(f"кольцо: центр {r['кольцо'][0]},{r['кольцо'][1]} радиус {r['кольцо'][2]}")
        for p in (r["взгляд"], r["руль"]):
            print(f"  {os.path.basename(p)}: {os.path.getsize(p)//1024} КБ")
