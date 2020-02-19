import ffmpeg as ff
import glob, os

directory = 'path/to/audios'

def wavToMp3(audio):
    (
    ff
    .input(audio)
    .output(audio + '.mp3')
    .run()
    )


def traverseConvert(dir):
    for root, dirs, files in os.walk(dir):
        for file in files:
            if file.endswith(".wav"):
                wavToMp3(os.path.join(root, file))

traverseConvert(directory)
