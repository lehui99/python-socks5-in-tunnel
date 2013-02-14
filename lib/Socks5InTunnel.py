import socket
import threading
import Queue
import urllib2
import random
import BaseHTTPServer
import CGIHTTPServer

class StringStream:
    def __init__(self, string = ''):
        self.string = string
    def read(self, bytesCount):
        if len(self.string) == 0:
            raise EOFError()
        content = self.string[ : bytesCount]
        self.string = self.string[bytesCount : ]
        return content
    def write(self, content):
        self.string += content
    def __str__(self):
        return self.string

class SocketStream:
    def __init__(self, socket):
        self.socket = socket
    def read(self, bytesCount = 65536):
        return self.socket.recv(bytesCount)
    def write(self, content):
        self.socket.sendall(content)

class Packer:
    def __init__(self, outStream = StringStream()):
        self.outStream = outStream
    def packNumber(self, number, bytesCount):
        for i in xrange(0, bytesCount):
            self.outStream.write(chr((number >> ((bytesCount - 1 - i) * 8)) & 0xff))
    def pack(self, content, lengthBytes = 3):
        self.packNumber(len(content), lengthBytes)
        self.outStream.write(content)

class Unpacker:
    def __init__(self, inStream = StringStream()):
        self.inStream = inStream
    def readFully(self, bytesCount):
        remains = bytesCount
        content = ''
        while remains != 0:
            read = self.inStream.read(remains)
            content += read
            remains -= len(read)
        return content
    def unpackNumber(self, bytesCount):
        number = 0
        for i in xrange(0, bytesCount):
            number |= ord(self.inStream.read(1)) << ((bytesCount - 1 - i) * 8)
        return number
    def unpack(self, lengthBytes = 3):
        length = self.unpackNumber(lengthBytes)
        return self.readFully(length)

class SockOperCmd:
    CONNECT_CMD = 0
    SEND_CMD = 1
    RECV_CMD = 2
    CLOSE_CMD = 3

class SocksException(Exception):
    pass

class SocksOperCli:
    def __init__(self, tunnel):
        self.tunnel = tunnel
    def connect(self, remoteHost, remotePort):
        packer = Packer()
        packer.packNumber(SocketOperationCommand.CONNECT_CMD, 1)
        packer.pack(remoteHost, 1)
        packer.packetNumber(remotePort, 2)
        unpacker = Unpacker(StringStream(self.tunnel(str(packer.outStream))))
        if unpacker.unpackNumber(1) != 1:
            raise SocksException()
        self.sessId = unpacker.unpackNumber(4)
    def send(self, content):
        packer = Packer()
        packer.packNumber(SocketOperationCommand.SEND_CMD, 1)
        packer.packNumber(self.sessId, 4)
        packer.pack(content)
        unpacker = Unpacker(StringStream(self.tunnel(str(packer.outStream))))
        if unpacker.unpackNumber(1) != 1:
            raise SocksException()
    def recv(self):
        packer = Packer()
        packer.packNumber(SocketOperationCommand.RECV_CMD, 1)
        packer.packNumber(self.sessId, 4)
        unpacker = Unpacker(StringStream(self.tunnel(str(packer.outStream))))
        if unpacker.unpackNumber(1) != 1:
            raise SocksException()
        return unpacker.unpack()
    def close(self):
        packer = Packer()
        packer.packNumber(SocketOperationCommand.CLOSE_CMD, 1)
        packer.packNumber(self.sessId, 4)
        unpacker = Unpacker(StringStream(self.tunnel(str(packer.outStream))))
        if unpacker.unpackNumber(1) != 1:
            raise SocksException()

class SocksSocketOper:
    def __init__(self, recvSize = 65536):
        self.recvSize = recvSize
    def connect(self, remoteHost, remotePort):
        self.socket = socket.socket()
        self.socket.connect((remoteHost, remotePort))
    def send(self, content):
        self.socket.send(content)
    def recv(self):
        return self.socket.recv(self.recvSize)
    def close(self):
        self.socket.close()

class SocksOperSvr:
    def __init__(self, sessId, operImpl = SocksSocketOper()):
        self.sessId = sessId
        self.operImpl = operImpl
    def __call__(self, cmd, unpacker, tunnel):
        doers = {
            CONNECT_CMD : self.doConnect,
            SEND_CMD : self.doSend,
            RECV_CMD : self.doRecv,
            CLOSE_CMD : self.doClose,
            }
        doers[cmd](unpacker, tunnel)
    def doConnect(self, unpacker, tunnel):
        remoteHost = unpacker.unpack(1)
        remotePort = unpacker.unpackNumber(2)
        packer = Packer()
        try:
            self.operImpl.connect(remoteHost, remotePort)
            packer.packNumber(1, 1)
        except Exception:
            packer.packNumber(0, 1)
        tunnel(str(packer.outStream))
    def doSend(self, unpacker, tunnel):
        content = unpacker.unpack()
        packer = Packer()
        try:
            self.operImpl.send(content)
            packer.packNumber(1, 1)
        except Exception:
            packer.packNumber(0, 1)
        tunnel(str(packer.outStream))
    def doRecv(self, unpacker, tunnel):
        packer = Packer()
        try:
            content = self.operImpl.recv()
            packer.packNumber(1, 1)
            packer.pack(content)
        except Exception:
            packer.packNumber(0, 1)
        tunnel(str(packer.outStream))
    def doClose(self, unpacker, tunnel):
        packer = Packer()
        try:
            self.operImpl.close()
            packer.packNumber(1, 1)
        except Exception:
            packer.packNumber(0, 1)
        tunnel(str(packer.outStream))

class SocksSvrSessMgr:
    def __init__(self, socksOperSvrGen = SocksOperSvr):
        self.socksOperSvrGen = socksOperSvrGen
        self.sessMap = {}
        self.sessId = 0
    def __call__(self, tunnel):
        unpacker = Unpacker(StringStream(tunnel()))
        cmd = unpacker.unpackNumber(1)
        if cmd != SockOperCmd.CONNECT_CMD:
            sessId = unpacker.unpackNumber(4)
            socksOperSvr = self.sessMap[self.sessId]
            if cmd == SockOperCmd.CLOSE_CMD:
                del self.sessMap[self.sessId]
        else:
            socksOperSvr = self.socksOperSvrGen(self.sessId)
            self.sessId += 1
            if self.sessId == 0x100000000:
                self.sessId = 0
        socksOperSvr(cmd, unpacker, tunnel)

class UrlTunnel:
    def __init__(self, url):
        self.url = url
    def __execute__(self, content):
        return urllib2.urlopen(self.url, content).read()

class ReadWriteTunnel:
    def __init__(self, content = ''):
        self.content = content
    def __execute__(self, content = None):
        if content == None:
            return self.content
        else:
            self.content = content

class SimpleHttpdTunnelHandler(CGIHTTPServer.CGIHTTPRequestHandler):
    def __init__(self, sessMgr, tunnelGen = ReadWriteTunnel):
        CGIHTTPServer.CGIHTTPRequestHandler.__init__(self)
        self.sessMgr = sessMgr
        self.tunnelGen = tunnelGen
    def do_POST(self):
        contentLength = int(self.headers['Content-Length'])
        unpacker = Unpacker(self.rfile)
        content = unpacker.readFully(contentLength)
        tunnel = self.tunnelGen(content)
        self.sessMgr(tunnel)
        self.send_response(200)
        self.send_header('Content-Length', str(len(tunnel.content)))
        self.end_headers()
        self.wfile.write(tunnel.content)

class SimpleHttpdTunnelSvr:
    def __init__(self, port = 80, handlerGen = SimpleHttpdTunnelHandler, sessMgrGen = SocksSvrSessMgr):
        self.handlerGen = handlerGen
        self.sessMgr = sessMgrGen()
        self.httpd = BaseHTTPServer.HTTPServer(('', port), self.handler)
    def handler(self):
        return self.handlerGen(self.sessMgr)
    def __execute__(self):
        self.httpd.serve_forever()

class Socks5CliOperImpl:
    def __init__(self, svrSocket, operImpl = SocksOperCli(UrlTunnel('http://127.0.0.1/'))):
        self.svrSocket = svrSocket
        self.operImpl = operImpl
    def __execute__(self):
        cliSocket, cliAddr = self.svrSocket.accept()
        threading.Thread(target = self.client, args = (cliSocket, )).start()
    def client(self, cliSocket):
        unpacker = Unpacker(SocketStream(cliSocket))
        packer = Packer(SocketStream(cliSocket))
        unpacker.unpackNumber(1)
        nmethods = unpacker.unpackNumber(1)
        unpacker.readFully(nmethods)
        packer.packNumber(5, 1)
        packer.packNumber(0, 1)
        unpacker.unpackNumber(1)
        cmd = unpacker.unpackNumber(1)
        if cmd != 1:    # not connect
            packer.packNumber(5, 1)
            packer.packNumber(7, 1)
            packer.packNumber(0, 1)
            packer.packNumber(1, 1)
            packer.packNumber(0, 6)
            cliSocket.close()
            return
        unpacker.unpackNumber(1)
        atyp = unpacker.unpackNumber(1)
        if atyp == 1:   # ipv4
            dstAddr = []
            for i in xrange(0, 4):
                dstAddr.append(str(unpacker.unpackNumber(1)))
            dstAddr = '.'.join(dstAddr)
        elif atyp == 3:   # domain
            dstAddr = unpacker.unpack(1)
        elif atyp == 4:   # ipv6
            dstAddr = []
            for i in xrange(0, 16):
                dstAddr.append(str(unpacker.unpackNumber(1)))
            dstAddr = ':'.join(dstAddr)
        else:
            packer.packNumber(5, 1)
            packer.packNumber(8, 1)
            packer.packNumber(0, 1)
            packer.packNumber(1, 1)
            packer.packNumber(0, 6)
            cliSocket.close()
            return
        dstPort = unpacker.unpackNumber(2)
        self.operImpl.connect(dstAddr, dstPort)
        threading.Thread(target = self.sending, args = (unpacker.outStream, ))
        self.recving(packer.inStream)
    def sending(self, inStream):
        while True:
            content = inStream.read()
            if len(content) < 1:
                break
            self.operImpl.send(content)
    def recving(self, outStream):
        while True:
            content = operImpl.recv()
            if len(content) < 1:
                break
            outStream.write(content)

class XorEncryptor:
    def __init__(self, key):
        self.key = key
    def __call__(self, content):
        result = ''
        for i in xrange(0, len(content)):
            result += chr(ord(content[i]) ^ ord(self.key[i % len(self.key)]))
        return result

XorDecryptor = XorEncryptor

class BufferedSocks5Operation:
    def __init__(self, operImpl, maxSendCount = 10, maxRecvCount = 10, maxIdle = 30):
        self.operImpl = operImpl
        self.sendBufs = Queue.Queue(maxSendCount)
        self.recvBufs = Queue.Queue(maxRecvCount)
        self.maxIdle = maxIdle
        self.idle = 0
    def connect(self, remoteHost, remotePort):
        self.operImpl.connect(remoteHost, remotePort)
        threading.Thread(target = self.sending).start()
        threading.Thread(target = self.recving).start()
    def send(self, content):
        self.sendBufs.put(content)
    def sending(self):
        try:
            while True:
                content = self.sendBufs.get()
                while not self.sendBufs.empty():
                    content += self.sendBufs.get()
                self.operImpl.send(content)
        finally:
            sendBufs = self.sendBufs
            self.sendBufs = None
            sendBufs.get_nowait()
    def recv(self):
        content = self.recvBufs.get()
        while not self.recvBufs.empty():
            content += self.recvBufs.get()
        return content
    def recving(self):
        try:
            while True:
                content = self.operImpl.recv()
                self.recvBufs.put(content)
        finally:
            recvBufs = self.recvBufs
            self.recvBufs = None
            recvBufs.put_nowait(None)
    def close(self):
        self.operImpl.close()
        sendBufs = self.sendBufs
        recvBufs = self.recvBufs
        self.sendBufs = None
        self.recvBufs = None
        try:
            if sendBufs != None:
                sendBufs.put_nowait(None)
        except Queue.Full:
            pass
        try:
            if sendBufs != None:
                sendBufs.get_nowait()
        except Queue.Empty:
            pass
        try:
            if recvBufs != None:
                recvBufs.put_nowait(None)
        except Queue.Full:
            pass
        try:
            if recvBufs != None:
                recvBufs.get_nowait()
        except Queue.Empty:
            pass
