// Set the video capture as a global variable.
let capture;

export const sketch = (p) => {
    p.setup = () => {
        p.describe('Video capture from the device webcam.');
        p.createCanvas(720, 400);

        // Use the createCapture() function to access the device's
        // camera and start capturing video.
        capture = p.createCapture(p.VIDEO);

        // Make the capture frame half of the canvas.
        capture.size(360, 200);

        // Use capture.hide() to remove the p5.Element object made
        // using createCapture(). The video will instead be rendered as
        // an image in draw().
        capture.hide();
    }

    p.draw = () => {
        // Set the background to gray.
        p.background(51);

        // Draw the resulting video capture on the canvas
        // with the invert filter applied.
        p.image(capture, 0, 0, 360, 400);
        p.filter(p.INVERT);
    }
}