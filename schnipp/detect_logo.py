#!/usr/bin/env python3

import numpy as np
import cv2


def show_image(img):
    cv2.imshow('image', img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

def create_blank(width, height):
    image = np.zeros((height, width, 1), np.uint8)
    image[:] = 255
    return image

def load_image(path):
    print(path)
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

def write_image(path, img):
    cv2.imwrite(path, img)

def get_shape(path):
    ref = load_image(path)
    return (ref.shape[1], ref.shape[0])

def calc_min(path_list):
    width, height = get_shape(path_list[0])
    img = create_blank(width, height)
    for f in path_list:
        img = cv2.min(img, load_image(f))
    return img

def dog_filter(img, ks1, ks2, sigma):
    g1 = cv2.GaussianBlur(img, (ks1, ks1), sigmaX=sigma, sigmaY=sigma)
    g2 = cv2.GaussianBlur(img, (ks2, ks2), sigmaX=sigma, sigmaY=sigma)
    return g1 - g2

def enhance_logo_feature(img):
    img = cv2.erode(img, np.ones((2, 2), np.uint8))
    img = cv2.dilate(img, np.ones((3, 3), np.uint8), iterations=3)
    img = cv2.dilate(img, np.ones((3, 3), np.uint8), iterations=3)
    img = cv2.erode(img, np.ones((3, 3), np.uint8), iterations=3)
    return img

def find_largest_area(img):
    cnts = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[-2]
    return cv2.boundingRect(max(cnts, key=cv2.contourArea))

def detect_logo(file_list):
    img = calc_min(file_list)
    img = dog_filter(img, 19, 5, 1.0)
    img = enhance_logo_feature(img)
    rect = find_largest_area(img)
    print(rect)
    return rect

if __name__ == '__main__':
    file_list = [
        '/media/data2/Dokumente/Programming/schnipp/screengrab_2.png',
        '/media/data2/Dokumente/Programming/schnipp/screengrab_3.png',
        #'/media/data2/Dokumente/Programming/schnipp/screengrab_4.png',
        '/media/data2/Dokumente/Programming/schnipp/screengrab_5.png',
        '/media/data2/Dokumente/Programming/schnipp/screengrab_6.png',
        #'/media/data2/Dokumente/Programming/schnipp/screengrab_7.png',
        #'/media/data2/Dokumente/Programming/schnipp/screengrab_8.png',
        '/media/data2/Dokumente/Programming/schnipp/screengrab_9.png',
        '/media/data2/Dokumente/Programming/schnipp/screengrab_10.png',
        #'/media/data2/Dokumente/Programming/schnipp/screengrab_11.png',
        '/media/data2/Dokumente/Programming/schnipp/screengrab_12.png',
        '/media/data2/Dokumente/Programming/schnipp/screengrab_13.png',
        '/media/data2/Dokumente/Programming/schnipp/screengrab_14.png',
    ]
    detect_logo(file_list)
