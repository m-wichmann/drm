import QtQuick 2.9
import QtQuick.Layouts 1.11
import QtQuick.Controls 2.4
import QtMultimedia 5.6
import QtQuick.Dialogs 1.3
import QtQml 2.4
import QtQuick.Window 2.2
import QtQuick.Extras 1.4
import Qt.labs.settings 1.1

Window {
    id: schnippWindow
    width: 1000
    height: 700
    title: qsTr('Schnipp!')
    visible: true
    //visibility: "FullScreen"
    visibility: "Maximized"

    Settings {
        id: settings
        property string defaultVideoFile: '/concat.mp4'
        property string defaultConfigFile: '/drm_dvr.cfg'
        property string lastDirectory: '.'
    }

    function formatTime(videoTime) {
        // Source: https://stackoverflow.com/a/6313008
        var sec_num = parseInt(videoTime/1000, 10); // don't forget the second param
        var hours   = Math.floor(sec_num / 3600);
        var minutes = Math.floor((sec_num - (hours * 3600)) / 60);
        var seconds = sec_num - (hours * 3600) - (minutes * 60);

        if (hours   < 10) {hours   = "0"+hours;}
        if (minutes < 10) {minutes = "0"+minutes;}
        if (seconds < 10) {seconds = "0"+seconds;}
        return hours+':'+minutes+':'+seconds;
    }

    Timer {
        /**
         * Refreshes elapsed time label and progress bar to show video position.
         **/
        id: updateTimer
        interval: 100; running: true; repeat: true
        onTriggered: {
            elapsedTimeLabel.text = formatTime(video.position) + ' / ' + formatTime(video.duration)
            videoProgressBar.value = video.position / video.duration
        }
    }

    Timer {
        id: exportTimer
        property int no: 0
        property int lifetime: 10
        property int oldPosition: 0
        property int stepTime: 0
    }

    function onDirectoryChosen(chosenDirectory) {
        // TODO: Find better way to handle path.
        settings.lastDirectory = chosenDirectory
        schnippWindow.title = `${qsTr('Schnipp!')} - ${chosenDirectory}`
        // TODO: Extract file name defaults to settings. 
        console.log('You chose: ' + chosenDirectory + settings.defaultVideoFile)
        // set internal variables for data from chosen directory
        video.source = chosenDirectory + settings.defaultVideoFile
        var JsonString = FileIO.readFile(chosenDirectory + settings.defaultConfigFile)
        console.log('Loaded JSON data: ' + JsonString)
        try {
            var JsonObject= JSON.parse(JsonString);
            if (JsonObject['crop'] !== null) {
                var cropData = JsonObject['crop']
                selectArea.bottomLetterboxBar = Math.floor(cropData[1] / 2)
                selectArea.topLetterboxBar = Math.floor(cropData[1] / 2)
            }
            if (JsonObject['delogo'] !== null) {
                var delogoData = JsonObject['delogo']
                selectArea.xv1 = delogoData[0]
                selectArea.yv1 = delogoData[1]
                selectArea.xv2 = delogoData[0] + delogoData[2]
                selectArea.yv2 = delogoData[1] + delogoData[3]
            }
            var cutlistData = JsonObject['cutlist']
            cutListModel.clear()
            for(var i = 0; i < cutlistData.length; i++) {
                var startTime = Math.round(parseFloat(cutlistData[i][0])*1000)
                var endTime = Math.round(parseFloat(cutlistData[i][1])*1000)
                cutListModel.append({'startTime': startTime, 'endTime': endTime})
            }
        }
        catch (e) {
            console.log(`Could not parse JSON file: ${e}`)
        }
        exportButton.enabled = true
        processButton.enabled = true
    }

    FileDialog {
        id: fileDialog
        title: qsTr('Choose a video file...')
        folder: settings.lastDirectory
        selectMultiple: false
        selectFolder: true
        selectExisting: true
        visible: false
        onAccepted: {
            onDirectoryChosen(fileDialog.folder)
        }
        onRejected: {
            console.log("Canceled")
        }
    }

    function onChooseFile() { 
        fileDialog.visible = true
    }

    function doPlay() {
        if (video.playbackState == MediaPlayer.PlayingState) {
            playButton.text = qsTr('Play')
            video.pause()
        }
        else if (video.playbackState == MediaPlayer.PausedState) {
            playButton.text = qsTr('Pause')
            video.play()
        }
        else if (video.playbackState == MediaPlayer.StoppedState) {
            playButton.text = qsTr('Pause')
            video.play()
        }
    }
    
    function doStop() {
        video.stop()
        playButton.text = qsTr('Play')
        selectArea.highlightLogo.destroy()
        selectArea.highlightLetterbox1.destroy()
        selectArea.highlightLetterbox2.destroy()
    }

    function doGoStart() {
        playButton.text = qsTr('Play')
        video.pause()
        video.seek(0)
    }

    function doGoEnd() {
        playButton.text = qsTr('Play')
        video.pause()
        video.seek(video.duration)
    }

    function onCutlistStartButton() {
        cutListModel.append({'startTime': video.position, 'endTime': 42})
    }

    function onCutlistEndButton() {
        cutListModel.get(cutListView.currentIndex).endTime = video.position
    }

    function seekVideo(delta) {
        var newPosition = video.position + delta
        if (newPosition < 0) {
            newPosition = 0
        }
        if (newPosition > video.duration) {
            newPosition = video.duration
        }
        video.seek(newPosition)
    }

    function handleExport() {
        console.log('Export all data to JSON file...')
        // create JSON object
        var cropValue = (selectArea.topLetterboxBar !== 0) ? [0, selectArea.topLetterboxBar + selectArea.bottomLetterboxBar] : null
        var delogoValue = (selectArea.xv1 !== 0) ? [selectArea.xv1, selectArea.yv1, selectArea.xv2-selectArea.xv1, selectArea.yv2-selectArea.yv1] : null
        var jsonOutput = {
            crop: cropValue,
            delogo: delogoValue,
            cutlist: []
        };
        // add all entries from cut list
        var i;
        for (i=0; i < cutListModel.count; i++) {
            var tmp = cutListModel.get(i)
            var startTime = tmp.startTime / 1000
            var endTime = tmp.endTime / 1000
            jsonOutput['cutlist'].push([startTime, endTime])
        }
        // output JSON to file
        var jsonString = JSON.stringify(jsonOutput, null, 4)
        console.log('Export configuration: ' + jsonString)
        FileIO.writeFile(settings.lastDirectory + settings.defaultConfigFile, jsonString)
    }

    function writeImageToFile() {
        exportTimer.no += 1
        console.log(`Export image no. ${exportTimer.no}`)
        if (exportTimer.no >= exportTimer.lifetime) {
            exportTimer.stop()
            video.seek(exportTimer.oldPosition)
            ImageProcessing.execute(10)
        }
        else {
            video.grabToImage(function(result) {
                var filename = `screengrab_${exportTimer.no}.png`
                console.log(filename)
                result.saveToFile(filename)
            });
            video.seek(exportTimer.no * exportTimer.stepTime)
            video.play()
            video.pause()
        }
    }

    function handleImageProcessing() {
        // select some images from video and process it to find logo
        selectArea.highlightLetterbox1.destroy()
        selectArea.highlightLetterbox2.destroy()
        if (selectArea.highlightLogo !== null) {
            selectArea.highlightLogo.destroy()
        }
        //
        ImageProcessing.processingReady.connect(function (x, y, width, height) {
            console.log(`Processing ready: (${x} ${y} ${width} ${height})`)
            selectArea.highlightLogo = highlightComponent.createObject(selectArea, {
                'x' : x,
                'y' : y,
                'width' : width,
                'height' : height,
                'color': 'yellow'
            });
        })
        // build timer to grab images
        exportTimer.interval = 3000;
        exportTimer.lifetime = 15
        var stepTime = Math.floor(video.duration / (exportTimer.lifetime + 3))
        console.log(`Step time for image export is ${stepTime}`)
        exportTimer.stepTime = stepTime
        exportTimer.no = 1
        exportTimer.oldPosition = video.position
        exportTimer.repeat = true;
        exportTimer.triggered.connect(writeImageToFile);
        // seek to first image to grab
        video.seek(exportTimer.stepTime * exportTimer.no)
        // start timer to grab following images
        exportTimer.start();
    }

    Component.onCompleted: {
        

        // check if a command line argument was given and open that directory if so        
        if (typeof args !== 'undefined') {
            console.log(`Command line arguments given: ${args}`)
            onDirectoryChosen(args)
            video.recalculateSize()
            selectArea.refreshHighlights()
        } 
    }
    
    Pane {
        id: mainPane
        anchors.fill: parent
        focus: true

        Keys.onPressed: {
            if (event.key == Qt.Key_Q) {
                console.log('Quitting Schnipp.')
                Qt.quit()
            }
            else if (event.key == Qt.Key_S) {
                onCutlistStartButton()
            }
            else if (event.key == Qt.Key_E) {
                onCutlistEndButton()
            }
            else if (event.key == Qt.Key_F) {
                handleExport()
            }
            else if (event.key == Qt.Key_Space) {
                doPlay()
            }

            if ((event.key == Qt.Key_Right) && (event.modifiers & Qt.ControlModifier))
                seekVideo(60000)
            else if ((event.key == Qt.Key_Right) && (event.modifiers & Qt.ShiftModifier))
                seekVideo(250)
            else if ((event.key == Qt.Key_Right) && (event.modifiers & Qt.AltModifier)) 
                doGoEnd()
            else if ((event.key == Qt.Key_Right))
                seekVideo(5000)

            if ((event.key == Qt.Key_Left) && (event.modifiers & Qt.ControlModifier))
                seekVideo(-60000)
            else if ((event.key == Qt.Key_Left) && (event.modifiers & Qt.ShiftModifier))
                seekVideo(-250)
            else if ((event.key == Qt.Key_Left) && (event.modifiers & Qt.AltModifier)) 
                doGoStart()
            else if ((event.key == Qt.Key_Left))
                seekVideo(-5000)
        }

        RowLayout {
            anchors.fill: parent
            spacing: 10

            ColumnLayout {
                Layout.fillHeight: true
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignLeft
                spacing: 10
                
                Video {
                    id: video
                    Layout.fillHeight: true
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignTop

                    focus: true
                    Rectangle {
                        anchors.top: parent.top
                        width: parent.width
                        height: parent.height
                        border.color: 'black'
                        color: '#000000ff'
                    }

                    onStopped: {
                        console.log('Video stopped.')
                        playButton.text = qsTr('Play')
                    }

                    onPositionChanged: {
                        if (video.position > 1000 && video.duration - video.position < 1000) {
                            playButton.text = qsTr('Play')
                            video.pause();
                        }
                    }

                    function recalculateSize() {
                        // calculate height of view depending on resolution of video and pixel size!
                        // TODO: Check what happens if height of video is larger than its width.
                        var videoHeightScreen = Math.ceil(width / video.metaData.pixelAspectRatio.width * video.metaData.pixelAspectRatio.height / video.metaData.resolution.width * video.metaData.resolution.height)
                        console.log('Calculated video height in View: ' + videoHeightScreen)
                        height = videoHeightScreen
                    }

                    onStatusChanged: {
                        if(status == MediaPlayer.Loaded) {
                            console.log('Video loaded.')
                            console.log('Loaded title: ' + video.metaData.title)
                            console.log('Loaded resolution: ' + video.metaData.resolution)
                            console.log('Loaded pixelAspectRatio: ' + video.metaData.pixelAspectRatio)
                            console.log('Loaded videoFrameRate: ' + video.metaData.videoFrameRate)
                            console.log('Width of Video view: ' + width)
                            console.log('Height of Video view: ' + height)
                            recalculateSize()
                            selectArea.refreshHighlights()
                            // play a very little bit of the video to show first frame in View
                            play()
                            pause()
                        }
                    }

                    onWidthChanged: {
                        if (video.status !== MediaPlayer.NoMedia) {
                            recalculateSize()
                            selectArea.refreshHighlights()
                        }
                    }

                    MouseArea {
                        /**
                        * Highlights a area marked by mouse.
                        *
                        * Source: https://stackoverflow.com/a/25865131
                        **/
                        id: selectArea;
                        anchors.fill: parent;
                        acceptedButtons: Qt.LeftButton | Qt.RightButton

                        property int stage: 1

                        // properties to be set in the GUI (in pixel of the video independent from size of View!)
                        property int topLetterboxBar: 0
                        property int bottomLetterboxBar: 0
                        property int xv1: 0
                        property int xv2: 0 
                        property int yv1: 0 
                        property int yv2: 0

                        function refreshHighlights() {
                            // build highlights for crop bars and logo from properties in case they were
                            // loaded from config file at the beginnning of editing
                            console.log('Preparing views for highlights...')
                            if (highlightLetterbox1 !== null) {
                                highlightLetterbox1.destroy()
                            }
                            if (highlightLetterbox2 !== null) {
                                highlightLetterbox2.destroy()
                            }
                            if (highlightLogo !== null) {
                                highlightLogo.destroy()
                            }
                            highlightLetterbox1 = highlightComponent.createObject(selectArea, {
                                'y': 0,
                                'height': parent.height / video.metaData.resolution.height * topLetterboxBar,
                                'color': 'green',
                                'anchors.left': selectArea.left,
                                'anchors.right': selectArea.right
                            });
                            highlightLetterbox2 = highlightComponent.createObject(selectArea, {
                                'y': selectArea.height - (parent.height / video.metaData.resolution.height * bottomLetterboxBar),
                                'height': parent.height / video.metaData.resolution.height * bottomLetterboxBar,
                                'color': 'green',
                                'anchors.left': selectArea.left,
                                'anchors.right': selectArea.right
                            });
                            highlightLogo = highlightComponent.createObject(selectArea, {
                                'x' : parent.width / video.metaData.resolution.width * xv1,
                                'y' : parent.height / video.metaData.resolution.height * yv1,
                                'width' : parent.width / video.metaData.resolution.width * (xv2-xv1),
                                'height' : parent.height / video.metaData.resolution.height * (yv2-yv1),
                                'color': 'yellow'
                            });
                        }

                        onPressed: {
                            if (mouse.button === Qt.LeftButton && stage == 1) {
                                if (highlightLetterbox1 !== null && highlightLetterbox2 !== null) {
                                    console.log('Letterbox rectangles already instantiated.')
                                }
                                else {
                                    // create two editable rectangles from the top down and the bottom up
                                    highlightLetterbox1 = highlightComponent.createObject(selectArea, {
                                        'y': selectArea.y,
                                        'height': Math.abs(selectArea.y - mouse.y),
                                        'color': 'green',
                                        'anchors.left': selectArea.left,
                                        'anchors.right': selectArea.right
                                    });
                                    highlightLetterbox2 = highlightComponent.createObject(selectArea, {
                                        'y': selectArea.height - Math.abs(selectArea.y - mouse.y),
                                        'height': Math.abs(selectArea.y - mouse.y),
                                        'color': 'green',
                                        'anchors.left': selectArea.left,
                                        'anchors.right': selectArea.right
                                    });
                                }
                            }
                            else if (mouse.button === Qt.LeftButton && stage == 2) {
                                if (highlightLogo !== null) {
                                    highlightLogo.destroy()
                                }
                                // create a new rectangle for the broadcaster logo
                                highlightLogo = highlightComponent.createObject(selectArea, {
                                    'x' : mouse.x,
                                    'y' : mouse.y,
                                    'color': 'yellow'
                                });
                            }
                        }
                        onPositionChanged: {
                            // on move, update the width of rectangle
                            if (stage == 1) {
                                if (mouse.y < parent.height/2) {
                                    highlightLetterbox1.height = Math.max(0, mouse.y - selectArea.y)
                                    highlightLetterbox2.y = selectArea.height - highlightLetterbox1.height
                                    highlightLetterbox2.height = highlightLetterbox1.height
                                    topLetterboxBar = video.metaData.resolution.height / parent.height * Math.max(0, mouse.y - selectArea.y)
                                    bottomLetterboxBar = topLetterboxBar
                                }
                                else {
                                    highlightLetterbox2.y = selectArea.height - Math.max(0, selectArea.height - mouse.y)
                                    highlightLetterbox2.height = Math.max(0, selectArea.height - mouse.y)
                                    bottomLetterboxBar = video.metaData.resolution.height / parent.height * Math.max(0, selectArea.height - mouse.y)
                                }
                            }
                            else if (stage == 2) {
                                var mouseX = mouse.x
                                var mouseY = mouse.y
                                // clip mouse coordinates on selectArea
                                if (mouseX > selectArea.width)
                                    mouseX = selectArea.width
                                if (mouseX < 0)
                                    mouseX = 0
                                if (mouseY > selectArea.height)
                                    mouseY = selectArea.height
                                if (mouseY < 0)
                                    mouseY = 0
                                // adjust highlight according to mouse motion
                                if (mouseX <= highlightLogo.x) {
                                    highlightLogo.width = highlightLogo.width + (highlightLogo.x - mouseX)
                                    highlightLogo.x = mouseX
                                }
                                else {
                                    highlightLogo.width = Math.abs(mouseX - highlightLogo.x);
                                }
                                if (mouseY <= highlightLogo.y) {
                                    highlightLogo.height = (highlightLogo.y - mouseY) + highlightLogo.height
                                    highlightLogo.y = mouseY
                                }
                                else {
                                    highlightLogo.height = Math.abs(mouseY - highlightLogo.y);
                                }
                            }
                        }
                        onReleased: {
                            if (mouse.button === Qt.LeftButton && stage == 1) {
                                console.log('Changed letterbox bars to: ' + topLetterboxBar + ', ' + bottomLetterboxBar)
                            }
                            else if (mouse.button === Qt.LeftButton && stage == 2) {
                                // calculate coordinates regarding video resolution and saving them in properties
                                var xs1 = highlightLogo.x
                                var xs2 = highlightLogo.x + highlightLogo.width
                                var ys1 = highlightLogo.y
                                var ys2 = highlightLogo.y + highlightLogo.height
                                xv1 = video.metaData.resolution.width / parent.width * xs1
                                xv2 = video.metaData.resolution.width / parent.width * xs2
                                yv1 = video.metaData.resolution.height / parent.height * ys1
                                yv2 = video.metaData.resolution.height / parent.height * ys2   
                                console.log('Choosen clipping on screen: (' + xs1 + ', ' + ys1 + ') to (' + xs2 + ', ' + ys2 + ').')
                                console.log('Choosen clipping on video: (' + xv1 + ', ' + yv1 + ') to (' + xv2 + ', ' + yv2 + ').')
                            }
                        }
                        onClicked: {
                            // handle context menu
                            if (mouse.button === Qt.RightButton && (mouse.y > Math.abs(selectArea.height - highlightLetterbox2.height) || mouse.y < highlightLetterbox1.height)) {
                                contextMenuCrop.x = mouse.x;
                                contextMenuCrop.y = mouse.y;
                                contextMenuCrop.open()
                            }
                            if (mouse.button === Qt.RightButton && selectArea.highlightLogo.contains(mapToItem(selectArea.highlightLogo, mouse.x, mouse.y))) {
                                console.log('Logo clicked')
                                contextMenuLogo.x = mouse.x;
                                contextMenuLogo.y = mouse.y;
                                contextMenuLogo.open()
                            }
                        }
                        Menu {
                            id: contextMenuCrop
                            MenuItem {
                                text: qsTr('Delete crop bars')
                                onTriggered: {
                                    console.log('Deleting crop bars.')
                                    selectArea.highlightLetterbox1.y = 0
                                    selectArea.highlightLetterbox1.height = 0
                                    selectArea.highlightLetterbox2.y = selectArea.height
                                    selectArea.highlightLetterbox2.height = 0
                                    selectArea.topLetterboxBar = 0
                                    selectArea.bottomLetterboxBar = 0
                                }
                            }
                        }
                        Menu {
                            id: contextMenuLogo
                            MenuItem {
                                text: qsTr('Delete logo')
                                onTriggered: {
                                    console.log('Deleting logo.')
                                    selectArea.highlightLogo.x = 0
                                    selectArea.highlightLogo.y = 0
                                    selectArea.highlightLogo.width = 0
                                    selectArea.highlightLogo.height = 0
                                    selectArea.xv1 = 0
                                    selectArea.xv2 = 0
                                    selectArea.yv1 = 0
                                    selectArea.yv2 = 0
                                }
                            }
                        }

                        property Rectangle highlightLogo : null;
                        property Rectangle highlightLetterbox1 : null;
                        property Rectangle highlightLetterbox2 : null;

                        Component {
                            id: highlightComponent

                            Rectangle {
                                id: highlightRectangle
                                opacity: 0.45;

                                MouseArea {
                                    id: logoMouseArea
                                    hoverEnabled: true
                                    width: 10
                                    height: 10
                                    anchors.bottom: parent.bottom
                                    anchors.right: parent.right

                                    property bool dragging: false

                                    cursorShape: "SizeFDiagCursor"
                                    onPressed: {
                                        if (selectArea.stage == 2 && containsMouse) {
                                            dragging = true
                                        }
                                    }
                                    onPositionChanged: {
                                        if (selectArea.stage == 2 && dragging) {
                                            parent.width = mouse.x - parent.x
                                            parent.height = mouse.y - parent.y
                                        }
                                    }
                                    onReleased: {
                                        if (selectArea.stage == 2) {
                                            dragging = false
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Pane {
                    anchors.margins: 10

                    Row {
                        spacing: 10

                        Button {
                            text:  qsTr('Choose directory...')
                            focusPolicy: Qt.NoFocus
                            background.anchors.fill: this
                            spacing: 40
                            onClicked: onChooseFile()
                        }
                        
                        Button {
                            id: playButton
                            text: qsTr('Play')
                            focusPolicy: Qt.NoFocus
                            onClicked: doPlay()
                        }
                        Button {
                            text: qsTr('Stop')
                            focusPolicy: Qt.NoFocus
                            onClicked: doStop()
                        }
                        Button {
                            text: qsTr('To Start')
                            focusPolicy: Qt.NoFocus
                            onClicked: doGoStart()
                        }
                        Button {
                            text: qsTr('Rewind')
                            focusPolicy: Qt.NoFocus
                            onClicked: {
                                video.seek(video.position - 5000)
                            }
                        }
                        Button {
                            text: qsTr('Forward')
                            focusPolicy: Qt.NoFocus
                            onClicked: {
                                video.seek(video.position + 5000)
                            }
                        }
                        Button {
                            text: qsTr('To End')
                            focusPolicy: Qt.NoFocus
                            onClicked: doGoEnd()
                        }

                        Label {
                            id: elapsedTimeLabel
                            text: ''
                            elide: Label.ElideRight
                            horizontalAlignment: Qt.AlignHCenter
                            verticalAlignment: Qt.AlignCenter
                            anchors.leftMargin: 20
                            anchors.verticalCenter: parent.verticalCenter
                            Layout.fillHeight: true
                            Layout.fillWidth: true
                        }

                        ProgressBar {
                            id: videoProgressBar
                            anchors.leftMargin: 20
                            anchors.verticalCenter: parent.verticalCenter
                            value: 0.5
                        }   
                    }
                }

                Pane {
                    Row {
                        spacing: 10

                        RadioButton {
                            checked: true
                            text: qsTr('Set Letterbox bars...')
                            focusPolicy: Qt.NoFocus
                            onClicked: {
                                selectArea.stage = 1
                                //cutListPane.visible = false
                            }
                        }
                        RadioButton {
                            text: qsTr('Set logo...')
                            focusPolicy: Qt.NoFocus
                            onClicked: {
                                selectArea.stage = 2
                                //cutListPane.visible = false
                            }
                        }
                        Button {
                            id: processButton
                            text: qsTr('Process image...')
                            focusPolicy: Qt.NoFocus
                            enabled: false
                            onClicked: {
                                handleImageProcessing()
                            }
                        }
                        Button {
                            id: exportButton
                            text: qsTr('Export...')
                            focusPolicy: Qt.NoFocus
                            enabled: false
                            onClicked: {
                                handleExport()
                            }
                        }
                    }
                }
            }

            Pane {
                id: cutListPane
                visible: true
                Layout.minimumWidth: 250
                Layout.maximumWidth: 250
                Layout.fillHeight: true
                Layout.fillWidth: true  
                Layout.alignment: Qt.AlignRight
                ScrollView {
                    anchors.fill: parent

                    Component {
                        id: highlight
                        Rectangle { 
                            width: parent.width
                            height: 25
                            color: "lightsteelblue"
                            radius: 5 
                            y: cutListView.currentItem.y
                            Behavior on y {
                                SpringAnimation {
                                    spring: 3
                                    damping: 0.2
                                }
                            }
                        }
                    }

                    ListView {
                        id: cutListView
                        anchors.fill: parent
                        width: parent.width
                        height: parent.height

                        keyNavigationWraps: true
                        highlightMoveDuration: 500
                        highlightMoveVelocity: -1
                        highlight: highlight
                        highlightFollowsCurrentItem: true
                        add: Transition {
                            NumberAnimation { properties: "x,y"; from: 100; duration: 500 }
                        }
                        populate: Transition {
                            NumberAnimation { properties: "x,y"; duration: 500 }
                        }
                        remove: Transition {
                            ParallelAnimation {
                                NumberAnimation { property: "opacity"; to: 0; duration: 500 }
                                NumberAnimation { properties: "x,y"; to: 100; duration: 500 }
                            }
                        }
                        
                        spacing: 15
                        displayMarginBeginning: 40
                        displayMarginEnd: 40
                        ScrollBar.vertical: ScrollBar {
                            active: true
                        }

                        ListModel {
                            id: cutListModel
                        }
                        model: cutListModel
                    
                        delegate: Rectangle {
                            objectName: "delegate"
                            width: parent.width
                            height: 25
                            color: '#000000ff'
                            Text {
                                anchors.left: parent.left
                                anchors.top: parent.top
                                anchors.bottom: parent.bottom
                                font.pixelSize: 14
                                text: `Start ${formatTime(startTime)} | End ${formatTime(endTime)}`
                                MouseArea {
                                    anchors.fill: parent
                                    onClicked: cutListView.currentIndex = index
                                }
                            }
                            Button {
                                id: xbutton
                                anchors.right: parent.right
                                width: 40
                                flat: true
                                highlighted: false
                                focusPolicy: Qt.NoFocus
                                contentItem: Text {
                                    text: 'X'
                                    opacity: enabled ? 1.0 : 0.3
                                    color: '#17a81a'
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    elide: Text.ElideRight
                                }
                                background: Rectangle {
                                    opacity: enabled ? 1.0 : 0.3
                                    border.color: '#17a81a'
                                    border.width: 1
                                    radius: 2
                                }
                                onClicked: {
                                    cutListModel.remove(index)
                                }
                            }
                            ListView.onAdd: {
                                cutListView.currentIndex = index
                            }
                        }

                        header: Rectangle { 
                            width: parent.width; height: 40
                            anchors.bottomMargin: 40
                            color: '#000000ff'
                            Text {
                                anchors.centerIn: parent
                                text: qsTr('Cut list')
                                font.pixelSize: 18
                            }
                        }

                        footer: Rectangle {
                            id: cutListViewFooter 
                            width: parent.width
                            height: 40
                            radius: 5 
                            anchors.topMargin: 40
                            Row {
                                Button {
                                    width: cutListViewFooter.width / 2
                                    height: cutListViewFooter.height
                                    focusPolicy: Qt.NoFocus
                                    text: qsTr('Set start time (S)')
                                    font.pixelSize: 12
                                    onClicked: {
                                        onCutlistStartButton()
                                    }
                                }
                                Button {
                                    width: cutListViewFooter.width / 2
                                    height: cutListViewFooter.height
                                    focusPolicy: Qt.NoFocus
                                    text: qsTr('Set end time (E)')
                                    font.pixelSize: 12
                                    onClicked: {
                                        onCutlistEndButton()
                                    }
                                }
                            }
                        } 
                    }
                }
            }
        }
    }
}
