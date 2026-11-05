import sys
from PIL import Image
pal = {}
def img(lines):
    im = Image.new('RGB', (320, 200))
    px = im.load()
    cols = [(0,0,0),(0,0,170),(0,170,0),(0,170,170),(170,0,0),(170,0,170),(170,85,0),(170,170,170),(85,85,85),(85,85,255),(85,255,85),(85,255,255),(255,85,85),(255,85,255),(255,255,85),(255,255,255)]
    for y, l in enumerate(lines[:200]):
        for x, ch in enumerate(l[:320]):
            c = (ord(ch) - 48) & 63
            px[x, y] = cols[c] if c < 16 else (c*4, c*4, c*4)
    return im
name = sys.argv[1]
a = open(name + '.expected').read().split('\n')
b = open(name + '.actual').read().split('\n')
diff = sum(1 for y in range(200) for x in range(320) if y < len(a) and y < len(b) and x < len(a[y]) and x < len(b[y]) and a[y][x] != b[y][x])
print(name, 'differing pixels:', diff, ' extra:', a[200:], b[200:])
A, B = img(a), img(b)
D = Image.new('RGB', (320, 200))
for y in range(200):
    for x in range(320):
        if y < len(a) and y < len(b) and x < len(a[y]) and x < len(b[y]) and a[y][x] != b[y][x]:
            D.putpixel((x, y), (255, 0, 0))
c = Image.new('RGB', (960, 200)); c.paste(A, (0, 0)); c.paste(B, (320, 0)); c.paste(D, (640, 0))
c = c.resize((1920, 400), Image.NEAREST); c.save(name + '_cmp.png')
