u"""
Convert Pascal VOC 2007+2012 detection dataset to HDF5.

Does not preserve full XML annotations.
Combines all VOC subsets (train, val test) with VOC2012 train for full
training set as done in Faster R-CNN paper.

Code based on:
https://github.com/pjreddie/darknet/blob/master/scripts/voc_label.py
"""

from __future__ import with_statement
from __future__ import absolute_import
import argparse
import os
import xml.etree.ElementTree as ElementTree

import h5py
import numpy as np
from io import open
from itertools import imap

sets_from_2007 = [(u'2007', u'train'), (u'2007', u'val')]
train_set = [(u'2012', u'train')]
val_set = [(u'2012', u'val')]
test_set = [(u'2007', u'test')]

classes = [
    u"aeroplane", u"bicycle", u"bird", u"boat", u"bottle", u"bus", u"car", u"cat",
    u"chair", u"cow", u"diningtable", u"dog", u"horse", u"motorbike", u"person",
    u"pottedplant", u"sheep", u"sofa", u"train", u"tvmonitor"
]

parser = argparse.ArgumentParser(
    description=u'Convert Pascal VOC 2007+2012 detection dataset to HDF5.')
parser.add_argument(
    u'-p',
    u'--path_to_voc',
    help=u'path to VOCdevkit directory',
    default=u'~/data/PascalVOC/VOCdevkit')


def get_boxes_for_id(voc_path, year, image_id):
    u"""Get object bounding boxes annotations for given image.

    Parameters
    ----------
    voc_path : str
        Path to VOCdevkit directory.
    year : str
        Year of dataset containing image. Either '2007' or '2012'.
    image_id : str
        Pascal VOC identifier for given image.

    Returns
    -------
    boxes : array of int
        bounding box annotations of class label, xmin, ymin, xmax, ymax as a
        5xN array.
    """
    fname = os.path.join(voc_path, u'VOC{}/Annotations/{}.xml'.format(year,
                                                                     image_id))
    with open(fname) as in_file:
        xml_tree = ElementTree.parse(in_file)
    root = xml_tree.getroot()
    boxes = []
    for obj in root.iter(u'object'):
        difficult = obj.find(u'difficult').text
        label = obj.find(u'name').text
        if label not in classes or int(
                difficult) == 1:  # exclude difficult or unlisted classes
            continue
        xml_box = obj.find(u'bndbox')
        bbox = (classes.index(label), int(xml_box.find(u'xmin').text),
                int(xml_box.find(u'ymin').text), int(xml_box.find(u'xmax').text),
                int(xml_box.find(u'ymax').text))
        boxes.extend(bbox)
    return np.array(
        boxes)  # .T  # return transpose so last dimension is variable length


def get_image_for_id(voc_path, year, image_id):
    u"""Get image data as uint8 array for given image.

    Parameters
    ----------
    voc_path : str
        Path to VOCdevkit directory.
    year : str
        Year of dataset containing image. Either '2007' or '2012'.
    image_id : str
        Pascal VOC identifier for given image.

    Returns
    -------
    image_data : array of uint8
        Compressed JPEG byte string represented as array of uint8.
    """
    fname = os.path.join(voc_path, u'VOC{}/JPEGImages/{}.jpg'.format(year,
                                                                    image_id))
    with open(fname, u'rb') as in_file:
        data = in_file.read()
    # Use of encoding based on: https://github.com/h5py/h5py/issues/745
    return np.fromstring(data, dtype=u'uint8')


def get_ids(voc_path, datasets):
    u"""Get image identifiers for corresponding list of dataset identifies.

    Parameters
    ----------
    voc_path : str
        Path to VOCdevkit directory.
    datasets : list of str tuples
        List of dataset identifiers in the form of (year, dataset) pairs.

    Returns
    -------
    ids : list of str
        List of all image identifiers for given datasets.
    """
    ids = []
    for year, image_set in datasets:
        id_file = os.path.join(voc_path, u'VOC{}/ImageSets/Main/{}.txt'.format(
            year, image_set))
        with open(id_file, u'r') as image_ids:
            ids.extend(imap(unicode.strip, image_ids.readlines()))
    return ids


def add_to_dataset(voc_path, year, ids, images, boxes, start=0):
    u"""Process all given ids and adds them to given datasets."""
    for i, voc_id in enumerate(ids):
        image_data = get_image_for_id(voc_path, year, voc_id)
        image_boxes = get_boxes_for_id(voc_path, year, voc_id)
        images[start + i] = image_data
        boxes[start + i] = image_boxes
    return i


def _main(args):
    voc_path = os.path.expanduser(args.path_to_voc)
    train_ids = get_ids(voc_path, train_set)
    val_ids = get_ids(voc_path, val_set)
    test_ids = get_ids(voc_path, test_set)
    train_ids_2007 = get_ids(voc_path, sets_from_2007)
    total_train_ids = len(train_ids) + len(train_ids_2007)

    # Create HDF5 dataset structure
    print u'Creating HDF5 dataset structure.'
    fname = os.path.join(voc_path, u'pascal_voc_07_12.hdf5')
    voc_h5file = h5py.File(fname, u'w')
    uint8_dt = h5py.special_dtype(
        vlen=np.dtype(u'uint8'))  # variable length uint8
    vlen_int_dt = h5py.special_dtype(
        vlen=np.dtype(int))  # variable length default int
    train_group = voc_h5file.create_group(u'train')
    val_group = voc_h5file.create_group(u'val')
    test_group = voc_h5file.create_group(u'test')

    # store class list for reference class ids as csv fixed-length numpy string
    voc_h5file.attrs[u'classes'] = np.string_(unicode.join(u',', classes))

    # store images as variable length uint8 arrays
    train_images = train_group.create_dataset(
        u'images', shape=(total_train_ids, ), dtype=uint8_dt)
    val_images = val_group.create_dataset(
        u'images', shape=(len(val_ids), ), dtype=uint8_dt)
    test_images = test_group.create_dataset(
        u'images', shape=(len(test_ids), ), dtype=uint8_dt)

    # store boxes as class_id, xmin, ymin, xmax, ymax
    train_boxes = train_group.create_dataset(
        u'boxes', shape=(total_train_ids, ), dtype=vlen_int_dt)
    val_boxes = val_group.create_dataset(
        u'boxes', shape=(len(val_ids), ), dtype=vlen_int_dt)
    test_boxes = test_group.create_dataset(
        u'boxes', shape=(len(test_ids), ), dtype=vlen_int_dt)

    # process all ids and add to datasets
    print u'Processing Pascal VOC 2007 datasets for training set.'
    last_2007 = add_to_dataset(voc_path, u'2007', train_ids_2007, train_images,
                               train_boxes)
    print u'Processing Pascal VOC 2012 training set.'
    add_to_dataset(
        voc_path,
        u'2012',
        train_ids,
        train_images,
        train_boxes,
        start=last_2007 + 1)
    print u'Processing Pascal VOC 2012 val set.'
    add_to_dataset(voc_path, u'2012', val_ids, val_images, val_boxes)
    print u'Processing Pascal VOC 2007 test set.'
    add_to_dataset(voc_path, u'2007', test_ids, test_images, test_boxes)

    print u'Closing HDF5 file.'
    voc_h5file.close()
    print u'Done.'


if __name__ == u'__main__':
    _main(parser.parse_args())
