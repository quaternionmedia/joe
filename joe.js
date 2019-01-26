var fft;
var mic;
var ffth = [];
var pmap = [];
var pmaphb = [];
var pmaph = [];
var histSize = 60;
var staff = [];
var recording = true;
var labels = false;
var setlist = [];
var current = 0;
var r = 0;
var g = 0;
var b = 0;
var h = 0;


function setup() {
    createCanvas(windowWidth, windowHeight);

    treb = loadImage("treble.png");
    filter(INVERT);
    bass = loadImage("bass.png");

    fft = new p5.FFT(0.2, 1024);
    mic = new p5.AudioIn();
//    print(mic.getSources());
//    mic.setSource(2);
    mic.start();
    mic.connect(fft);

    pmap = pnoDist(88, 12, 440);

    for (var m = 0; m < 88; m++) {
        if (m == 23 || m == 27 || m == 30 || m == 33 || m == 37 || m == 44 || m == 47 || m == 51 || m == 54 || m == 57) {
            append(staff, map(m, 0, 88, height - 100, 100));
        }
    }

    textAlign(CENTER);

    setlist = [{
        "genre": "Joe - the Realtime Audio Visualizer",
        "composer": "Peter Kagstrom",
        "title": "Sheet Music Visualizer",
        "year": "2016",
        "range": "Allow microphone access for a rough transcription",
        "r": 100,
        "g": 100,
        "b": 10,
        "h": 0
    }, {
        "genre": "Baroque",
        "composer": "J.S. Bach",
        "title": "The Well-Tempered Clavier, Prelude in C",
        "year": "1722",
        "range": "1600–1750",
        "r": 125,
        "g": 125,
        "b": 125,
        "h": 0
    }, {
        "genre": "Classical",
        "composer": "Wolfgang Amadeus Mozart",
        "title": "Fantasy in D minor",
        "year": "1782",
        "range": "1730-1820",
        "r": 150,
        "g": 150,
        "b": 64,
        "h": 0
    },	{
	"genre": "Romantic",
	"composer": "Franz Liszt",
	"title": "Consolation #3",
	"year": "1850",
	"range": "1780-1910",
	"r": 0,
	"g": 150,
	"b": 100,
	"h": 0
},
	{
        "genre": "Impressionist",
        "composer": "Claude-Achille Debussy",
        "title": "Suite Bergamasque",
        "year": "1908",
        "range": "1875-1925",
        "r": 64,
        "g": 150,
        "b": 150,
        "h": 0
    }, {
        "genre": "Ragtime",
        "composer": "Scott Joplin",
        "title": "Easy Winners",
        "year": "1901",
        "range": "1895-1917",
        "r": 75,
        "g": 50,
        "b": 155,
        "h": 0
    }, {
        "genre": "Early Jazz",
        "composer": "George Gershwin",
        "title": "Rhapsody in Blue",
        "year": "1924",
        "range": "1917-1940s",
        "r": 30,
        "g": 64,
        "b": 85,
        "h": 0
    }, 	{
	"genre": "Stride",
	"composer": "Art Tatum",
	"title": "Blue Moon",
	"year": "1955",
	"range": "1920s-1950s",
	"r": 190,
	"g": 40,
	"b": 0,
	"h": 0
    },	{
        "genre": "Modern Jazz",
        "composer": "Dave Brubeck",
        "title": "Blue Rondo A la Turk",
        "year": "1959",
        "range": "1940s-1970s",
        "r": 64,
        "g": 64,
        "b": 200,
        "h": 0
    },	{
	"genre": "Modern",
	"composer": "Adam Guettel",
	"title": "The Light in the Piazza - Overture",
	"year": "2003",
	"range": "1950s-present",
	"r": 190,
	"g": 100,
	"b": 150,
	"h": 0
    },	{
        "genre": "Present",
        "composer": "Peter Kagstrom",
        "title": "Improvisation",
        "year": "2018",
        "range": "right now",
        "r": 64,
        "g": 64,
        "b": 64,
        "h": 0
    }]

}

function draw() {
    if (pmaph.length > 2000) {
        pmaph.length = 2000;
    }
    background(0);

    //console.log(setlist[current]["composer"]);
    fill(125);
    textSize(60);
    text(setlist[current]["genre"], width / 2, 90);
    textSize(25);
    text(setlist[current]["range"], width / 2, 150);
    text(setlist[current]["composer"], width / 7, 250);
    text(setlist[current]["year"], 8 * width / 9, 250);
    textSize(55);
    text(setlist[current]["title"], width / 2, 250);


    this.spectrum = fft.analyze();

    if (recording) {
        for (var k = 0; k < pmap.length; k++) {
            pmaphb[k] = fft.getEnergy(pmap[k]);
        }

        pmaph.unshift(pmaphb);
        pmaphb = [];
    }

    this.pmapL = 0;
    if (pmaph.length < histSize) {
        this.pmapL = pmaph.length
    } else {
        this.pmapL = histSize;
    }

    for (var s = 0; s < staff.length; s++) {
        stroke(255);
        line(0, staff[s], width, staff[s]);
    }
    treb.resize(height/5, height/5);
    bass.resize(height/6, height/6);

    image(treb, 5, .35 * height);
    image(bass, 5, .541 * height);
   for (var m = 0; m < pmapL; m++) {
        for (var n = 0; n < pmaph[m].length; n++) {
            this.xy = logMap(pmaph[m][n], 10, 255, 1, 20);
            r = setlist[current]["r"];
            //console.log(setlist[current]["r"]);
            g = setlist[current]["g"];
            b = setlist[current]["b"];
            //this.xy = map(pmaph[m][n], 10, 255, 5, 20);

            //stroke(this.xy);
            this.px = map(m, 0, pmapL, width - 100, 100);
            this.py = map(n, 0, 88, height - 100, 100);
            //point(this.px, this.py);

            //this.px = 20 + m * 3;
            //this.py = height - 20 - n * 3
            //point(this.px, this.py);
            noStroke();
            //fill(255, 125);

            if (n < 76) {
                if (pmaph[m][n] > 150 && 2 * pmaph[m][n + 12] > pmaph[m][n]) {
                    b += 64;
                }
            }


            if (n < 69) {
                if (pmaph[m][n] > 150 && 2 * pmaph[m][n + 19] > pmaph[m][n]) {
                    b += 125;
                }
            }

            if (n < 64) {
                if (pmaph[m][n] > 150 && 2 * pmaph[m][n + 24] > pmaph[m][n]) {
                    b += 64;
                }
            }
            if (n < 60) {
                if (pmaph[m][n] > 150 && 2 * pmaph[m][n + 28] > pmaph[m][n]) {
                    b += 63;
                }
            }
            if (n < 57) {
                if (pmaph[m][n] > 150 && 3 * pmaph[m][n + 31] > pmaph[m][n]) {
                    g += 64;
                    r += 64;
                }
            }
            if (n < 54) {
                if (pmaph[m][n] > 150 && 3 * pmaph[m][n + 34] > pmaph[m][n]) {
                    g += 64;
                    r += 64;
                }
            }
            if (n > 64) {
                if (pmaph[m][n] > 200) {
                    r = 0;
                    g = 64;
                    b = 0;
                }
            }


            fill(r, g, b, 125);





            //fill(255,64);
            if (labels) {
                text(pmaph[m][n], this.px, this.py);
            }
            ellipse(this.px, this.py, this.xy, this.xy);
        }
    }
}

function logMap(_v, _vmin, _vmax, _omin, _omax) {
    this.u = _vmax - _vmin;
    this.m = exp((_v * log(this.u)) / this.u);
    return map(this.m, _vmin, _vmax, _omin, _omax);
}


function pnoDist(_numKeys, _split, _center) {
    this.fs = [];
    for (var i = 0; i < _numKeys; i++) {
        fs[i] = pow(2, (i - (_numKeys / 2 + 5)) / _split) * _center;
    }
    return this.fs;
}

function keyTyped() {
    if (key === 'l') {
        labels != labels;
    }
}

function keyPressed() {
    if (keyCode == BACKSPACE) {
        recording = !recording;
    }
    if (keyCode === RIGHT_ARROW) {
        if (current < setlist.length - 1) {
            current++;
        }
    }
    if (keyCode === LEFT_ARROW) {
        if (current > 0) {
            current--;
        }
    }
}
