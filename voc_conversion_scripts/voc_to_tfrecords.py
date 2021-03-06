u"""Convert Pascal VOC 2007+2012 detection dataset to TFRecords.
Does not preserve full XML annotations.
Combines all VOC 2007 subsets (train, val) with VOC2012 for training.
Uses VOC2012 val for val and VOC2007 test for test.

Code based on:
https://github.com/pjreddie/darknet/blob/master/scripts/voc_label.py
https://github.com/tensorflow/models/blob/master/inception/inception/data/build_image_data.py
"""

from __future__ import division
from __future__ import with_statement
from __future__ import absolute_import
import argparse
import os
import xml.etree.ElementTree as ElementTree
from datetime import datetime

import numpy as np
import tensorflow as tf

from voc_to_hdf5 import get_ids
from io import open

sets_from_2007 = [(u'2007', u'train'), (u'2007', u'val')]
train_set = [(u'2012', u'train'), (u'2012', u'val')]
test_set = [(u'2007', u'test')]

classes = [
    u"aeroplane", u"bicycle", u"bird", u"boat", u"bottle", u"bus", u"car", u"cat",
    u"chair", u"cow", u"diningtable", u"dog", u"horse", u"motorbike", u"person",
    u"pottedplant", u"sheep", u"sofa", u"train", u"tvmonitor"
]

parser = argparse.ArgumentParser(
    description=u'Convert Pascal VOC 2007+2012 detection dataset to TFRecords.')
parser.add_argument(
    u'-p',
    u'--path_to_voc',
    help=u'path to Pascal VOC dataset',
    default=u'~/data/PascalVOC/VOCdevkit')

# Small graph for image decoding
decoder_sess = tf.Session()
image_placeholder = tf.placeholder(dtype=tf.string)
decoded_jpeg = tf.image.decode_jpeg(image_placeholder, channels=3)


def process_image(image_path):
    u"""Decode image at given path."""
    with open(image_path, u'rb') as f:
        image_data = f.read()
    image = decoder_sess.run(decoded_jpeg,
                             feed_dict={image_placeholder: image_data})
    assert len(image.shape) == 3
    height = image.shape[0]
    width = image.shape[2]
    assert image.shape[2] == 3
    return image_data, height, width


def process_anno(anno_path):
    u"""Process Pascal VOC annotations."""
    with open(anno_path) as f:
        xml_tree = ElementTree.parse(f)
    root = xml_tree.getroot()
    size = root.find(u'size')
    height = float(size.find(u'height').text)
    width = float(size.find(u'width').text)
    boxes = []
    for obj in root.iter(u'object'):
        difficult = obj.find(u'difficult').text
        label = obj.find(u'name').text
        if label not in classes or int(
                difficult) == 1:  # exclude difficult or unlisted classes
            continue
        xml_box = obj.find(u'bndbox')
        bbox = {
            u'class': classes.index(label),
            u'y_min': float(xml_box.find(u'ymin').text) / height,
            u'x_min': float(xml_box.find(u'xmin').text) / width,
            u'y_max': float(xml_box.find(u'ymax').text) / height,
            u'x_max': float(xml_box.find(u'xmax').text) / width
        }
        boxes.append(bbox)
    return boxes


def convert_to_example(image_data, boxes, filename, height, width):
    u"""Convert Pascal VOC ground truth to TFExample protobuf.

    Parameters
    ----------
    image_data : bytes
        Encoded image bytes.
    boxes : dict
        Bounding box corners and class labels
    filename : string
        Path to image file.
    height : int
        Image height.
    width : int
        Image width.

    Returns
    -------
    example : protobuf
        Tensorflow Example protobuf containing image and bounding boxes.
    """
    box_classes = [b[u'class'] for b in boxes]
    box_ymin = [b[u'y_min'] for b in boxes]
    box_xmin = [b[u'x_min'] for b in boxes]
    box_ymax = [b[u'y_max'] for b in boxes]
    box_xmax = [b[u'x_max'] for b in boxes]
    encoded_image = [tf.compat.as_bytes(image_data)]
    base_name = [tf.compat.as_bytes(os.path.basename(filename))]

    example = tf.train.Example(features=tf.train.Features(feature={
        u'filename':
        tf.train.Feature(bytes_list=tf.train.BytesList(value=base_name)),
        u'height':
        tf.train.Feature(int64_list=tf.train.Int64List(value=[height])),
        u'width':
        tf.train.Feature(int64_list=tf.train.Int64List(value=[width])),
        u'classes':
        tf.train.Feature(int64_list=tf.train.Int64List(value=box_classes)),
        u'y_mins':
        tf.train.Feature(float_list=tf.train.FloatList(value=box_ymin)),
        u'x_mins':
        tf.train.Feature(float_list=tf.train.FloatList(value=box_xmin)),
        u'y_maxes':
        tf.train.Feature(float_list=tf.train.FloatList(value=box_ymax)),
        u'x_maxes':
        tf.train.Feature(float_list=tf.train.FloatList(value=box_xmax)),
        u'encoded':
        tf.train.Feature(bytes_list=tf.train.BytesList(value=encoded_image))
    }))
    return example


def get_image_path(voc_path, year, image_id):
    u"""Get path to image for given year and image id."""
    return os.path.join(voc_path, u'VOC{}/JPEGImages/{}.jpg'.format(year,
                                                                   image_id))


def get_anno_path(voc_path, year, image_id):
    u"""Get path to image annotation for given year and image id."""
    return os.path.join(voc_path, u'VOC{}/Annotations/{}.xml'.format(year,
                                                                    image_id))


def process_dataset(name, image_paths, anno_paths, result_path, num_shards):
    u"""Process selected Pascal VOC dataset to generate TFRecords files.

    Parameters
    ----------
    name : string
        Name of resulting dataset 'train' or 'test'.
    image_paths : list
        List of paths to images to include in dataset.
    anno_paths : list
        List of paths to corresponding image annotations.
    result_path : string
        Path to put resulting TFRecord files.
    num_shards : int
        Number of shards to split TFRecord files into.
    """
    shard_ranges = np.linspace(0, len(image_paths), num_shards + 1).astype(int)
    counter = 0
    for shard in xrange(num_shards):
        # Generate shard file name
        output_filename = u'{}-{:05d}-of-{:05d}'.format(name, shard, num_shards)
        output_file = os.path.join(result_path, output_filename)
        writer = tf.python_io.TFRecordWriter(output_file)

        shard_counter = 0
        files_in_shard = xrange(shard_ranges[shard], shard_ranges[shard + 1])
        for i in files_in_shard:
            image_file = image_paths[i]
            anno_file = anno_paths[i]

            # processes image + anno
            image_data, height, width = process_image(image_file)
            boxes = process_anno(anno_file)

            # convert to example
            example = convert_to_example(image_data, boxes, image_file, height,
                                         width)

            # write to writer
            writer.write(example.SerializeToString())

            shard_counter += 1
            counter += 1

            if not counter % 1000:
                print u'{} : Processed {:d} of {:d} images.'.format(
                    datetime.now(), counter, len(image_paths))
        writer.close()
        print u'{} : Wrote {} images to {}'.format(
            datetime.now(), shard_counter, output_filename)

    print u'{} : Wrote {} images to {} shards'.format(datetime.now(), counter,
                                                     num_shards)


def _main(args):
    u"""Locate files for train and test sets and then generate TFRecords."""
    voc_path = args.path_to_voc
    voc_path = os.path.expanduser(voc_path)
    result_path = os.path.join(voc_path, u'TFRecords')
    print u'Saving results to {}'.format(result_path)

    train_path = os.path.join(result_path, u'train')
    test_path = os.path.join(result_path, u'test')

    train_ids = get_ids(voc_path, train_set)  # 2012 trainval
    test_ids = get_ids(voc_path, test_set)  # 2007 test
    train_ids_2007 = get_ids(voc_path, sets_from_2007)  # 2007 trainval
    total_train_ids = len(train_ids) + len(train_ids_2007)
    print u'{} train examples and {} test examples'.format(total_train_ids,
                                                          len(test_ids))

    train_image_paths = [
        get_image_path(voc_path, u'2012', i) for i in train_ids
    ]
    train_image_paths.extend(
        [get_image_path(voc_path, u'2007', i) for i in train_ids_2007])
    test_image_paths = [get_image_path(voc_path, u'2007', i) for i in test_ids]

    train_anno_paths = [get_anno_path(voc_path, u'2012', i) for i in train_ids]
    train_anno_paths.extend(
        [get_anno_path(voc_path, u'2007', i) for i in train_ids_2007])
    test_anno_paths = [get_anno_path(voc_path, u'2007', i) for i in test_ids]

    process_dataset(
        u'train',
        train_image_paths,
        train_anno_paths,
        train_path,
        num_shards=60)
    process_dataset(
        u'test', test_image_paths, test_anno_paths, test_path, num_shards=20)


if __name__ == u'__main__':
    _main(parser.parse_args(args))
