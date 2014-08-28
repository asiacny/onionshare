from __future__ import division
import os, sys, subprocess, inspect, platform, argparse, threading, time, math, inspect, platform, urllib2
from PyQt4 import QtCore, QtGui

import common

try:
    import onionshare
except ImportError:
    sys.path.append(os.path.abspath(common.onionshare_gui_dir+"/.."))
    import onionshare
from onionshare import strings, helpers, web

from file_selection import FileSelection
from server_status import ServerStatus
from downloads import Downloads
from options import Options

class Application(QtGui.QApplication):
    def __init__(self):
        platform = helpers.get_platform()
        if platform == 'Tails' or platform == 'Linux':
            self.setAttribute(QtCore.Qt.AA_X11InitThreads, True)
        QtGui.QApplication.__init__(self, sys.argv)

class OnionShareGui(QtGui.QWidget):
    def __init__(self, qtapp, app):
        super(OnionShareGui, self).__init__()
        self.qtapp = qtapp
        self.app = app

        self.setWindowTitle('OnionShare')
        self.setWindowIcon(window_icon)

    def send_files(self, filenames=None):
        # file selection
        self.file_selection = FileSelection()
        if filenames:
            for filename in filenames:
                self.file_selection.file_list.add_file(filename)

        # server status
        self.server_status = ServerStatus(self.qtapp, self.app, web, self.file_selection)
        self.server_status.server_started.connect(self.file_selection.server_started)
        self.server_status.server_started.connect(self.start_server)
        self.server_status.server_stopped.connect(self.file_selection.server_stopped)
        self.server_status.server_stopped.connect(self.stop_server)
        self.file_selection.file_list.files_updated.connect(self.server_status.update)

        # downloads
        self.downloads = Downloads()

        # options
        self.options = Options(web)

        # main layout
        self.layout = QtGui.QVBoxLayout()
        self.layout.addLayout(self.file_selection)
        self.layout.addLayout(self.server_status)
        self.layout.addLayout(self.downloads)
        self.layout.addLayout(self.options)
        self.setLayout(self.layout)
        self.show()

        # check for requests frequently
        self.timer = QtCore.QTimer()
        QtCore.QObject.connect(self.timer, QtCore.SIGNAL("timeout()"), self.check_for_requests)
        self.timer.start(500)

    def start_server(self):
        # start the hidden service
        try:
            self.app.start_hidden_service(gui=True)
        except onionshare.NoTor as e:
            alert(e.args[0], QtGui.QMessageBox.Warning)
            self.server_status.stop_server()
            return
        except onionshare.TailsError as e:
            alert(e.args[0], QtGui.QMessageBox.Warning)
            self.server_status.stop_server()
            return

        # start onionshare service in new thread
        t = threading.Thread(target=web.start, args=(self.app.port, self.app.stay_open, True))
        t.daemon = True
        t.start()

        # prepare the files for sending
        web.set_file_info(self.file_selection.file_list.filenames)
        self.app.cleanup_filenames.append(web.zip_filename)

        self.server_status.start_server_finished()

    def stop_server(self):
        # to stop flask, load http://127.0.0.1:<port>/<shutdown_slug>/shutdown
        urllib2.urlopen('http://127.0.0.1:{0}/{1}/shutdown'.format(self.app.port, web.shutdown_slug)).read()
        self.app.cleanup()

        self.server_status.stop_server_finished()

    def check_for_requests(self):
        self.update()
        # only check for requests if the server is running
        if self.server_status.status != self.server_status.STATUS_STARTED:
            return

        events = []

        done = False
        while not done:
            try:
                r = web.q.get(False)
                events.append(r)
            except web.Queue.Empty:
                done = True

        for event in events:
            #if event["path"] != '/favicon.ico':
            #    pass
            #if event["type"] == web.REQUEST_LOAD:
            #    pass

            if event["type"] == web.REQUEST_DOWNLOAD:
                self.downloads.add_download(event["data"]["id"], web.zip_filesize)

            elif event["type"] == web.REQUEST_PROGRESS:
                self.downloads.update_download(event["data"]["id"], web.zip_filesize, event["data"]["bytes"])

                # is the download complete?
                if event["data"]["bytes"] == web.zip_filesize:
                    # close on finish?
                    if not web.get_stay_open():
                        self.server_status.stop_server()

def alert(msg, icon=QtGui.QMessageBox.NoIcon):
    dialog = QtGui.QMessageBox()
    dialog.setWindowTitle("OnionShare")
    dialog.setWindowIcon(window_icon)
    dialog.setText(msg)
    dialog.setIcon(icon)
    dialog.exec_()

def main():
    strings.load_strings()

    # start the Qt app
    global qtapp
    qtapp = Application()

    # parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--local-only', action='store_true', dest='local_only', help=strings._("help_local_only"))
    parser.add_argument('--stay-open', action='store_true', dest='stay_open', help=strings._("help_stay_open"))
    parser.add_argument('--debug', action='store_true', dest='debug', help=strings._("help_debug"))
    parser.add_argument('--filenames', metavar='filenames', nargs='+', help=strings._('help_filename'))
    args = parser.parse_args()

    filenames = args.filenames
    if filenames:
        for i in range(len(filenames)):
            filenames[i] = os.path.abspath(filenames[i])

    local_only = bool(args.local_only)
    stay_open = bool(args.stay_open)
    debug = bool(args.debug)

    # validation
    if filenames:
        valid = True
        for filename in filenames:
            if not os.path.exists(filename):
                alert(strings._("not_a_file").format(filename))
                valid = False
        if not valid:
            sys.exit()

    # create the onionshare icon
    global window_icon
    window_icon = QtGui.QIcon("{0}/static/logo.png".format(common.onionshare_gui_dir))

    # start the onionshare app
    web.set_stay_open(stay_open)
    app = onionshare.OnionShare(debug, local_only, stay_open)

    # clean up when app quits
    def shutdown():
        app.cleanup()
    qtapp.connect(qtapp, QtCore.SIGNAL("aboutToQuit()"), shutdown)

    # launch the gui
    gui = OnionShareGui(qtapp, app)
    gui.send_files(filenames)

    # all done
    sys.exit(qtapp.exec_())

if __name__ == '__main__':
    main()
