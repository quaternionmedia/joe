class Note():
    """ Note class to store the note properties. \n
        Properties: \n
            pitch: int, midi pitch. \n
            note: str, note name. \n
            duration: list, duration of note. \n
            start_time: list, list of start times. \n
    """
    def __init__(self):
        self.pitch: int = 0
        self.note: str = ""
        self.start_dur: list[list] = []
