#!/usr/bin/env python
"""
make_confidence_report.py
Usage:
  python make_confidence_report_spsa.py model.joblib

  where model.joblib is a file created by cleverhans.serial.save containing
  a picklable cleverhans.model.Model instance.

This script will run the model on a variety of types of data and save a
report to model_report.joblib. The report can be later loaded by another
script using cleverhans.serial.load. The format of the report is a dictionary.
Each dictionary key is the name of a type of data:
  clean : Clean data
  mc: MaxConfidence SPSA adversarial examples
Each value in the dictionary contains an array of bools indicating whether
the model got each example correct and an array containing the confidence
that the model assigned to each prediction.

This script works by running a single MaxConfidence attack on each example.
( https://openreview.net/forum?id=H1g0piA9tQ )
The MaxConfidence attack uses the SPSA optimizer.
This is not intended to be a generic strong attack; rather it is intended
to be a test for gradient masking.
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import logging
import time

import tensorflow as tf
from tensorflow.python.platform import flags

from cleverhans.attacks import MaxConfidence, SPSA
from cleverhans.evaluation import correctness_and_confidence
from cleverhans.serial import load
from cleverhans.utils import set_log_level
from cleverhans.utils_tf import silence
from cleverhans.confidence_report import devices, print_stats
from cleverhans.confidence_report import make_confidence_report
from cleverhans.confidence_report import BATCH_SIZE
from cleverhans.confidence_report import TRAIN_START
from cleverhans.confidence_report import TRAIN_END
from cleverhans.confidence_report import TEST_START
from cleverhans.confidence_report import TEST_END
from cleverhans.confidence_report import WHICH_SET
from cleverhans.confidence_report import NB_ITER
from cleverhans.confidence_report import REPORT_PATH

silence()

FLAGS = flags.FLAGS

def make_confidence_report_spsa(filepath, train_start=TRAIN_START,
                                train_end=TRAIN_END,
                                test_start=TEST_START, test_end=TEST_END,
                                batch_size=BATCH_SIZE, which_set=WHICH_SET,
                                report_path=REPORT_PATH,
                                nb_iter=NB_ITER):
  """
  Load a saved model, gather its predictions, and save a confidence report.


  This function works by running a single MaxConfidence attack on each example,
  using SPSA as the underyling optimizer.
  This is not intended to be a strong generic attack.
  It is intended to be a test to uncover gradient masking.

  :param filepath: path to model to evaluate
  :param train_start: index of first training set example to use
  :param train_end: index of last training set example to use
  :param test_start: index of first test set example to use
  :param test_end: index of last test set example to use
  :param batch_size: size of evaluation batches
  :param which_set: 'train' or 'test'
  :param nb_iter: Number of iterations of PGD to run per class
  """

  # Set TF random seed to improve reproducibility
  tf.set_random_seed(1234)

  # Set logging level to see debug information
  set_log_level(logging.INFO)

  # Create TF session
  sess = tf.Session()

  if report_path is None:
    assert filepath.endswith('.joblib')
    report_path = filepath[:-len('.joblib')] + "_spsa_report.joblib"

  with sess.as_default():
    model = load(filepath)
  assert len(model.get_params()) > 0
  factory = model.dataset_factory
  factory.kwargs['train_start'] = train_start
  factory.kwargs['train_end'] = train_end
  factory.kwargs['test_start'] = test_start
  factory.kwargs['test_end'] = test_end
  dataset = factory()

  center = dataset.kwargs['center']
  max_val = dataset.kwargs['max_val']
  value_range = max_val * (1. + center)
  min_value = 0. - center * max_val

  if 'CIFAR' in str(factory.cls):
    base_eps = 8. / 255.
  elif 'MNIST' in str(factory.cls):
    base_eps = .3
  else:
    raise NotImplementedError(str(factory.cls))

  mc_params = {'eps': base_eps * value_range,
               'nb_iter': nb_iter,
               'clip_min': min_value,
               'clip_max': max_val}


  x_data, y_data = dataset.get_set(which_set)

  report = {}

  spsa = SPSA(model, sess)
  mc = MaxConfidence(model, sess=sess, base_attacker=spsa)

  jobs = [('clean', None, None, None),
          ('mc', mc, mc_params, None)]

  for job in jobs:
    name, attack, attack_params, job_batch_size = job
    if job_batch_size is None:
      job_batch_size = batch_size
    t1 = time.time()
    packed = correctness_and_confidence(sess, model, x_data, y_data,
                                        batch_size=job_batch_size, devices=devices,
                                        attack=attack,
                                        attack_params=attack_params)
    t2 = time.time()
    print("Evaluation took", t2 - t1, "seconds")
    correctness, confidence = packed

    report[name] = {
        'correctness' : correctness,
        'confidence'  : confidence
        }

    print_stats(correctness, confidence, name)


  save(report_path, report)

def main(argv=None):
  """
  Make a confidence report and save it to disk.
  """
  try:
    _name_of_script, filepath = argv
  except ValueError:
    raise ValueError(argv)
  make_confidence_report_spsa(filepath=filepath, test_start=FLAGS.test_start,
                              test_end=FLAGS.test_end, which_set=FLAGS.which_set,
                              report_path=FLAGS.report_path,
                              nb_iter=FLAGS.nb_iter,
                              batch_size=FLAGS.batch_size)

if __name__ == '__main__':
  flags.DEFINE_integer('train_start', TRAIN_START, 'Starting point (inclusive)'
                       'of range of train examples to use')
  flags.DEFINE_integer('train_end', TRAIN_END, 'Ending point (non-inclusive) '
                       'of range of train examples to use')
  flags.DEFINE_integer('test_start', TEST_START, 'Starting point (inclusive) of range'
                       ' of test examples to use')
  flags.DEFINE_integer('test_end', TEST_END, 'End point (non-inclusive) of range'
                       ' of test examples to use')
  flags.DEFINE_integer('nb_iter', NB_ITER, 'Number of iterations of PGD')
  flags.DEFINE_string('which_set', WHICH_SET, '"train" or "test"')
  flags.DEFINE_string('report_path', REPORT_PATH, 'Path to save to')
  flags.DEFINE_integer('batch_size', BATCH_SIZE,
                       'Batch size for most jobs')
  tf.app.run()