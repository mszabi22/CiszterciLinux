/* Kolibri Linux - telepítő diavetítés (Calamares slideshow API 2) */
import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation {
    id: presentation

    function nextSlide() {
        presentation.goToNextSlide();
    }

    Timer {
        id: advanceTimer
        interval: 9000
        running: presentation.activatedInCalamares
        repeat: true
        onTriggered: nextSlide()
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#0d2136" }
                GradientStop { position: 1.0; color: "#06111e" }
            }
        }
        Column {
            anchors.centerIn: parent
            width: parent.width * 0.82
            spacing: 18
            Item {
                width: parent.width
                height: 112
                Image {
                    anchors.centerIn: parent
                    height: parent.height
                    width: parent.width
                    source: "bird.png"
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#e8eef4"
                font.pixelSize: 28
                font.bold: true
                text: "Üdv a Kolibri Linuxban"
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#b4c2d0"
                font.pixelSize: 16
                text: "Stabil. Egyszerű. Kezdőbarát. A telepítés néhány percig tart, közben bemutatjuk, mire számíthatsz."
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#0d2136" }
                GradientStop { position: 1.0; color: "#06111e" }
            }
        }
        Column {
            anchors.centerIn: parent
            width: parent.width * 0.82
            spacing: 18
            Item {
                width: parent.width
                height: parent.parent.height * 0.5
                Image {
                    anchors.centerIn: parent
                    height: parent.height
                    width: parent.width
                    source: "desktop.png"
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#e8eef4"
                font.pixelSize: 28
                font.bold: true
                text: "Ismerős elrendezés"
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#b4c2d0"
                font.pixelSize: 16
                text: "Alul a tálca, balra a Start menü, így az első percben otthon érzed magad. A Win+E a fájlkezelőt nyitja."
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#0d2136" }
                GradientStop { position: 1.0; color: "#06111e" }
            }
        }
        Column {
            anchors.centerIn: parent
            width: parent.width * 0.82
            spacing: 18
            Item {
                width: parent.width
                height: 112
                Image {
                    anchors.centerIn: parent
                    height: parent.height
                    width: parent.width
                    source: "bird.png"
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#e8eef4"
                font.pixelSize: 28
                font.bold: true
                text: "Stabil Debian alap"
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#b4c2d0"
                font.pixelSize: 16
                text: "A Kolibri Linux a Debian stabil ágára épül. A biztonsági frissítések automatikusan települnek, a Timeshift pedig segít, ha vissza kell lépni."
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#0d2136" }
                GradientStop { position: 1.0; color: "#06111e" }
            }
        }
        Column {
            anchors.centerIn: parent
            width: parent.width * 0.82
            spacing: 18
            Item {
                width: parent.width
                height: 112
                Image {
                    anchors.centerIn: parent
                    height: parent.height
                    width: parent.width
                    source: "bird.png"
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#e8eef4"
                font.pixelSize: 28
                font.bold: true
                text: "Titkosítás és adatvédelem"
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#b4c2d0"
                font.pixelSize: 16
                text: "A Signal, a Tuta Mail, a KeePassXC, a VeraCrypt és a Kleopatra már a rendszerben van, a tűzfal pedig alapból be van kapcsolva."
            }
        }
    }

    Slide {
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#0d2136" }
                GradientStop { position: 1.0; color: "#06111e" }
            }
        }
        Column {
            anchors.centerIn: parent
            width: parent.width * 0.82
            spacing: 18
            Item {
                width: parent.width
                height: 112
                Image {
                    anchors.centerIn: parent
                    height: parent.height
                    width: parent.width
                    source: "bird.png"
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#e8eef4"
                font.pixelSize: 28
                font.bold: true
                text: "Az első indítástól kész"
            }
            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                color: "#b4c2d0"
                font.pixelSize: 16
                text: "A legfrissebb LibreOffice, a Brave böngésző és a szoftverközpont vár rád. A telepítés végén indítsd újra a gépet, és vedd ki a pendrive-ot."
            }
        }
    }

    function onActivate() { }
    function onLeave() { }
}
