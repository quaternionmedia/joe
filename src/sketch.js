var fft;
var mic;
const ffth = [];
var pmap = [];
var pmaphb = [];
const pmaph = [];
const histSize = 125;
const staff = [];
var r, g, b = 0;
var current = 0;
var setlist = [];


function setup() {
    createCanvas(windowWidth, windowHeight);
    

    // Create a button and attach an event listener
    const startButton = createButton('Joe, go!');
    startButton.position(10, 10);
    startButton.mousePressed(startAudio);

    textAlign(CENTER);

    pmap = new Float32Array(pnoDist(88, 12, 440));
    setlist = [{
        "genre": "",
        "composer": "",
        "title": "",
        "year": "",
        "range": "",
        "r":0,
        "g":0,
        "b":0
    },{
        "genre": "Baroque",
        "composer": "J.S. Bach",
        "title": "The Well-Tempered Clavier, Prelude in C",
        "year": "1722",
        "range": "1600–1750",
        "r":125,
        "g":125,
        "b":125
    }, {
        "genre": "Classical",
        "composer": "Wolfgang Amadaus Mozart",
        "title": "Fantasy in D minor",
        "year": "1782",
        "range": "1730-1820",
        "r":125,
        "g":125,
        "b":150
    }, {
        "genre": "Romantic",
        "composer": "Frederic Chopin",
        "title": "Opus 69, Waltz No. 2",
        "year": "1829",
        "range": "1780-1910",
        "r":0,
        "g":0,
        "b":0
    }, {
        "genre": "Impressionist",
        "composer": "Claude-Achille Debussy",
        "title": "Childrens Corner, Doctor gradus ad Parnassum",
        "year": "1908",
        "range": "1875-1925",
        "r":0,
        "g":0,
        "b":0
    }, {
        "genre": "Ragtime",
        "composer": "Scott Joplin",
        "title": "Easy Winners",
        "year": "1901",
        "range": "1895-1917",
        "r":0,
        "g":0,
        "b":0
    }, {
        "genre": "Modern",
        "composer": "George Gershwin",
        "title": "Prelude No. 2",
        "year": "1926",
        "range": "1890-1975",
        "r":0,
        "g":0,
        "b":0
    }, {
        "genre": "Jazz",
        "composer": "Dave Brubeck",
        "title": "Blue Rondo A la Turk",
        "year": "1959",
        "range": "1920s-1970s",
        "r":0,
        "g":0,
        "b":0
    }, {
        "genre": "Present",
        "composer": "Peter Kagstrom",
        "title": "Improvisation",
        "year": "2016",
        "range": "right now",
        "r":0,
        "g":0,
        "b":0
    }]


}

function startAudio() {
    fft = new p5.FFT();
    mic = new p5.AudioIn();
    mic.start();
    mic.connect(fft);
}

function draw() {
    background(0);

    // fill(125);
    // textSize(40);
    // text(setlist[current]["genre"], width / 2, 30);
    // textSize(15);
    // text(setlist[current]["range"], width / 2, 50);
    // text(setlist[current]["composer"], width / 4, 90);
    // text(setlist[current]["year"], 3 * width / 4, 90);
    // textSize(25);
    // text(setlist[current]["title"], width / 2, 90);



    if (pmaph.length > 2000) {
        pmaph.length = 2000;
    }

    if (mic) {
        this.spectrum = fft.analyze();


        for (var k = 0; k < pmap.length; k++) {
            pmaphb[k] = fft.getEnergy(pmap[k]);
        }
        pmaph.unshift(pmaphb);
        pmaphb = [];

        this.pmapL = 0;
        if (pmaph.length < histSize) {
            this.pmapL = pmaph.length
        } else {
            this.pmapL = histSize;
        }

        fill(255, 125);
        for (var m = 0; m < pmapL; m++) {
            if (m == 23 || m == 27 || m == 30 || m == 33 || m == 37 || m == 44 || m == 47 || m == 51 || m == 54 || m == 57) {
                stroke(125);
                strokeWeight(3);
                line(0, map(m, 0, 88, height - 100, 100), width, map(m, 0, 88, height - 100, 100));
            }

            noStroke();

            for (var n = 0; n < pmaph[m].length; n++) {

                fill(r, g, b);
                const xy = logMap(pmaph[m][n], 10, 255, 0, 20);
                const px = map(m, 0, histSize, width - 100, 100);
                const py = map(n, 0, 88, height - 100, 100);
                ellipse(px, py, xy, xy);
            }
        }
    }
}

function grandStaff() {

}


function logMap(_v, _vmin, _vmax, _omin, _omax) {
    const u = _vmax - _vmin;
    const m = exp((_v * log(u)) / u);
    return map(m, _vmin, _vmax, _omin, _omax);
}


function pnoDist(_numKeys, _split, _center) {
    const fs = [];
    for (var i = 0; i < _numKeys; i++) {
        fs[i] = pow(2, (i - (_numKeys / 2 + 5)) / _split) * _center;
    }
    return fs;
}

function keyPressed() {
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