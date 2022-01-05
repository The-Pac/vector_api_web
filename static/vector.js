let gUserAgent = window.navigator.userAgent;
let gIsMicrosoftBrowser = gUserAgent.indexOf('MSIE ') > 0 || gUserAgent.indexOf('Trident/') > 0 || gUserAgent.indexOf('Edge/') > 0;
let gSkipFrame = false;

if (gIsMicrosoftBrowser) {
    document.getElementById("vectorImageMicrosoftWarning").style.display = "block";
}

function postHttpRequest(url, dataSet) {
    let xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    xhr.send(JSON.stringify(dataSet));
}

function ping() {
    document.getElementById("vectorImageId").textContent = ""
}

function updateVector() {
    if (gIsMicrosoftBrowser && !gSkipFrame) {
        gSkipFrame = true;
        document.getElementById("vectorImageId").src = "vectorImage?" + (new Date()).getTime();
    } else if (gSkipFrame) {
        gSkipFrame = false;
    }
    let xhr = new XMLHttpRequest();

    xhr.open("POST", "updateVector", true);
    xhr.send(null);
}

setInterval(updateVector, 60);


function handleKeyActivity(e, actionType) {
    let keyCode = (e.keyCode ? e.keyCode : e.which);
    let hasShift = (e.shiftKey ? 1 : 0)
    let hasCtrl = (e.ctrlKey ? 1 : 0)
    let hasAlt = (e.altKey ? 1 : 0)


    postHttpRequest(actionType, {keyCode, hasShift, hasCtrl, hasAlt})
}

document.addEventListener("keydown", function (e) {
    handleKeyActivity(e, "keydown")
});
document.addEventListener("keyup", function (e) {
    handleKeyActivity(e, "keyup")
});

