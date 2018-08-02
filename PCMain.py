import sys, os
from random import shuffle
from time import sleep
from queue import Queue
from threading import Thread, Lock, Event
from _io import BytesIO

import requests
from urllib import parse
from lxml import html
from PIL import Image, ImageFilter
from PyQt4 import uic
from PyQt4.QtGui import *
from PyQt4.QtCore import Qt, QSize, pyqtSignal, pyqtSlot


class JobItem:
    def __init__(self):
        self.src = None
        self.item_obj = None
        self.file_name = None


class MyMainWindow(QMainWindow):
    # 这里为了偷懒，把一些固定量放在本类的共有属性里
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64.0.3282.119 Safari/537.36'
    START_URL = 'http://tu.jiachong.net/gaoqingtaotu/'
    OUTPUT_DIR = 'output'

    PIC_SIZE = 180
    # GRID_SIZE = 190
    PAGE_LIMIT = 25
    LABEL_FMT = '总数：{}'

    SIG_UPDATE_ITEM_PIC = pyqtSignal(tuple)

    def __init__(self):
        super(MyMainWindow, self).__init__()

        # ----从ui文件加载Qt Designer设计好的界面----
        uic.loadUi('MainWindow.ui', self)

        # ----事件关联操作----
        self.btnLoadNextBatch.clicked.connect(self.cmd_load_next_batch)
        self.btnClearList.clicked.connect(self.cmd_clear_list)
        self.lwPicsList.itemDoubleClicked.connect(self.cmd_lw_double_click)
        # 自定义信号关联事件
        self.SIG_UPDATE_ITEM_PIC.connect(self.update_item_pic)

        # ----初始化队列与线程等----
        self.url_queue = Queue()
        self.job_queue = Queue()
        self.data_list = []
        self.data_lock = Lock()
        self.running_event = Event()
        self.running_event.set()
        # 单线程收集页面链接
        self.job_submitter_thread = Thread(target=self.job_submitter, daemon=True)
        self.job_submitter_thread.start()
        # 多线程收集页面链接（参考）
        # self.job_submitter_threads = []
        # for i in range(3):
        #     t = Thread(target=self.job_submitter, daemon=True)
        #     t.start()
        #     self.job_submitter_threads.append(t)
        # 单线程加载图片
        self.job_worker_thread = Thread(target=self.job_worker, daemon=True)
        self.job_worker_thread.start()
        # 多线程加载图片（参考）
        # self.job_worker_threads = []
        # for i in range(3):
        #     t = Thread(target=self.job_worker, daemon=True)
        #     t.start()
        #     self.job_worker_threads.append(t)

        # ----确保目标目录存在----
        try:
            os.mkdir(self.OUTPUT_DIR)
        except:
            pass

        # ----放入起始URL，线程接收后会自动开始爬取----
        self.url_queue.put(self.START_URL)
        self.statusBar().showMessage('开始工作...')

    # 用于处理解析网页中的图片链接的方法
    def job_submitter(self):
        url_queue = self.url_queue
        job_queue = self.job_queue
        while True:
            item = url_queue.get()
            if not item:
                break

            # 如果有事件标记，则在此阻塞等待
            self.running_event.wait()

            url = item
            try:
                r = requests.get(url, headers={'User-Agent': self.USER_AGENT})
                r.raise_for_status()  # 请求出错，则直接抛出错误
                r.encoding = 'utf-8'
                # print(r.text)  # debug
                htree = html.fromstring(r.content)

                # 处理选择进入图集页面
                new_urls = htree.xpath("//ul[@class='liL']/li/a/@href")
                shuffle(new_urls)
                for i in new_urls:
                    url_queue.put(i)

                # 处理图集页面中的图片链接
                new_img_srcs = htree.xpath("//div[@class='articleBody']//img/@src")
                shuffle(new_img_srcs)
                for i in new_img_srcs:
                    # 新建自定义任务项
                    job = JobItem()
                    job.src = i
                    # 准备好用于界面显示的QListWidgetItem
                    job.item_obj = QListWidgetItem()
                    job.item_obj.setSizeHint(QSize(self.PIC_SIZE, self.PIC_SIZE))
                    # job.item_obj.setTextAlignment(Qt.AlignCenter)
                    # 将job添加到队列
                    job_queue.put(job)

                # 处理翻页
                new_page_urls = htree.xpath("//div[@class='pages']/ul/li/a[@href!='#']/@href")
                new_page_urls = [parse.urljoin(url, i) for i in new_page_urls]
                shuffle(new_page_urls)
                for i in new_page_urls:
                    url_queue.put(i)
            except:
                pass

            url_queue.task_done()

            # 等待间隔，避免网络请求太频繁
            sleep(0.5)

    # 用于加载图片、添加显示到界面上
    def job_worker(self):
        job_queue = self.job_queue
        while True:
            item = job_queue.get()
            if not item:
                break

            # 如果有事件标记，则在此阻塞等待
            self.running_event.wait()

            job = item
            try:
                url = job.src
                file_name = os.path.basename(parse.urlparse(url).path)
                file_name = os.path.join(self.OUTPUT_DIR, file_name)
                job.file_name = file_name
                r = requests.get(url, headers={'User-Agent': self.USER_AGENT})
                r.raise_for_status()  # 请求出错，则直接抛出错误

                # 将获取到的图片数据写入到文件
                self.statusBar().showMessage('正在加载图片({})...'.format(os.path.basename(file_name)))
                with open(file_name, 'wb') as fp:
                    fp.write(r.content)

                # 保存图片文件名到数据列表中
                with self.data_lock:
                    self.data_list.append(file_name)

                # 被注释掉的操作会抛出在非主线程中不能操作主界面元素的错误
                # item_obj = job.item_obj
                # item_obj.setIcon(QIcon(file_name))
                # 改为用自定义“信号——槽”来实现
                self.SIG_UPDATE_ITEM_PIC.emit((job,))
            except:
                # print(tb.format_exc())
                pass

            job_queue.task_done()

            # 判断是否需要设置等待事件
            with self.data_lock:
                if len(self.data_list) % self.PAGE_LIMIT == 0:
                    self.running_event.clear()
                    self.statusBar().showMessage('已暂停...')

            # 等待间隔，避免网络请求太频繁
            sleep(0.2)

    # 界面相关，更新界面上指定的标签文字
    def update_label_text(self, text):
        self.lbHint.setText(text)

    # 界面相关，更新列表中项目的图片
    @pyqtSlot(tuple)
    def update_item_pic(self, args):
        job_item = args[0]
        file_name = job_item.file_name
        item_obj = job_item.item_obj

        # ----此处二次处理图片为缩略图，避免内存溢出，并使用高斯模糊滤镜----
        # PIL打开图片
        img = Image.open(file_name)
        # 锁定长宽比缩小图片
        w, h = img.size
        ratio = self.PIC_SIZE / (h if h >= w else w)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.ANTIALIAS)
        w, h = img.size  # 顺便重新获取大小，供后面计算使用
        # 高斯模糊
        img = img.filter(ImageFilter.GaussianBlur(radius=2))
        # 暂存于内存中，使用BytesIO
        bio = BytesIO()
        img.save(bio, 'jpeg')
        # 关闭PIL图像句柄
        img.close()
        # 利用QPainter将图片在QImage内居中显示
        qimg = QImage.fromData(bio.getvalue())
        new_qimg = QImage(self.PIC_SIZE, self.PIC_SIZE, QImage.Format_ARGB32)
        new_qimg.fill(Qt.white)  # 填充白色作为背景，否则显示效果会有些诡异
        pnt = QPainter()
        pnt.begin(new_qimg)  # 经测试，在slot里面一定要用QPainter.begin()、QPainter.end()，否则会报错“QPaintDevice: Cannot destroy paint device that is being painted”
        pnt.drawImage(max((self.PIC_SIZE - w) / 2, 0), max((self.PIC_SIZE - h) / 2, 0), qimg)  # 居中画图
        pnt.end()
        # 将QImage显示在QListWidgetItem上
        icon = QIcon(QPixmap.fromImage(new_qimg))
        item_obj.setIcon(icon)
        # 将QListWidgetItem对象添加到界面上的QListWidget中
        with self.data_lock:
            self.lwPicsList.addItem(item_obj)
            self.update_label_text(self.LABEL_FMT.format(len(self.data_list)))
        # 关闭BytesIO句柄
        bio.close()

    # 界面相关，“加载下一批”按钮点击事件
    def cmd_load_next_batch(self):
        self.running_event.set()
        self.statusBar().showMessage('开始加载下一批...')

    # 界面相关，“清空列表”按钮点击事件
    def cmd_clear_list(self):
        if self.running_event.is_set():
            # 不允许本批图片正在加载时清空列表
            QMessageBox.warning(self.centralWidget(), '温馨提示', '请等待本批图片加载完毕后再操作，谢谢！', QMessageBox.Ok)
            return

        with self.data_lock:
            self.lwPicsList.clear()
            self.data_list.clear()
            self.update_label_text(self.LABEL_FMT.format(len(self.data_list)))

    # 界面相关，列表项双击事件
    def cmd_lw_double_click(self):
        sels = self.lwPicsList.selectedItems()
        if len(sels) > 0:
            for i in sels:
                with self.data_lock:
                    # 获取索引（与self.data_list对应即可）
                    ind = self.lwPicsList.indexFromItem(i)
                    ind = ind.row()
                    # 获取对应图片文件名
                    file_name = self.data_list[ind]
                    # 通过系统关联程序打开图片文件
                    os.startfile(file_name)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = MyMainWindow()
    window.show()
    sys.exit(app.exec_())
