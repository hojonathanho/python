#!/usr/bin/env python

import numpy as np
from brett2 import ros_utils
from brett2.ros_utils import Marker
import jds_utils
from jds_utils import conversions
import rospy
import match
import lfd, yaml, os, h5py
from lfd import warping, registration, recognition

class Globals:
  rviz = None
  handles = []
  tf_listener = None
  isinstance(rviz, ros_utils.RvizWrapper)
  #isinstance(tf_listener, ...)
  def __init__(self): raise
  @staticmethod
  def setup():
    if Globals.rviz is None: Globals.rviz = ros_utils.RvizWrapper.create()
    if Globals.tf_listener is None: Globals.tf_listener = ros_utils.get_tf_listener()

def select_from_list(lst, prompt='Choose from the following options: '):
    strlist = [str(item) for item in lst]
    while True:
      print prompt + " ".join("(%s)"%item for item in strlist)
      resp = raw_input("> ")
      if resp not in strlist:
        print "invalid response. try again."
      else:
        return lst[strlist.index(resp)]            

def load_demo(taskname='overhand_knot', demos_list_file='knot_demos.yaml', seg_name=None):
  data_dir = os.path.join(os.path.dirname(lfd.__file__), "data")
  with open(os.path.join(data_dir, demos_list_file),"r") as fh: 
    task_info = yaml.load(fh)
  H5FILE = os.path.join(data_dir, task_info[taskname]["db_file"])
  demos_file = h5py.File(H5FILE,"r")
  demos = warping.group_to_dict(demos_file)    
  demos_file.close()
  if seg_name is None:
    seg_name = select_from_list(sorted(demos.keys()))
  demo = demos[seg_name]
  demo["cloud_xyz_ds"], ds_inds = recognition.downsample(demo["cloud_xyz"])
  demo["cloud_xyz"] = np.squeeze(demo["cloud_xyz"])
  return demo

def load_cloud_from_sensor(input_topic, frame):
  import sensor_msgs.msg
  msg = rospy.wait_for_message(input_topic, sensor_msgs.msg.PointCloud2)
  xyz, rgb = ros_utils.pc2xyzrgb(msg)
  xyz = xyz.reshape(-1,3)
  xyz = ros_utils.transform_points(xyz, Globals.tf_listener, frame, msg.header.frame_id)
  return xyz

def main():
  import argparse
  parser = argparse.ArgumentParser(description='Tool for aligning a demo to a live point cloud')
  parser.add_argument('--demos_list_file', default='knot_demos.yaml')
  parser.add_argument('--taskname', default='overhand_knot')
  parser.add_argument('--seg_name', default=None)
  parser.add_argument('--nonrigid', action='store_true')
  parser.add_argument('--frame', default='camera_rgb_frame')
  parser.add_argument('--input_topic', default='/preprocessor/kinect1/points')
  parser.add_argument('--show_shape_contexts', action='store_true')
  parser.add_argument('--warp_once_only', action='store_true')
  args = parser.parse_args()

  if rospy.get_name() == '/unnamed':
    rospy.init_node('publish_single_cloud', disable_signals=True)
  Globals.setup()

  demo = load_demo(args.taskname, args.demos_list_file, args.seg_name)

  # align demo to test in a loop
  prev_params = None
  keep_warping = True
  while True:
    xyz_new = load_cloud_from_sensor(args.input_topic, args.frame)
    if xyz_new.size == 0: continue

    xyz_demo_ds = demo['cloud_xyz_ds']
    xyz_new_ds = recognition.downsample(xyz_new)[0]

    if keep_warping:
      if args.nonrigid:
        f = registration.tps_rpm(xyz_demo_ds, xyz_new_ds, plotting=False,reg_init=1,reg_final=.1,n_iter=21, verbose=False)
      else:
        f = registration.Rigid3d()
        f.fit(xyz_demo_ds, xyz_new_ds, prev_params)
        prev_params = f.get_params()

      if args.warp_once_only:
        keep_warping = False

    if args.show_shape_contexts:
      shape_context_costs = recognition.match_and_calc_shape_context(xyz_demo_ds, xyz_new_ds, normalize_costs=True)
      colors = [(c, 1-c, 0, 1) for c in shape_context_costs]
    else:
      colors = [(1, 0, 0, 1)] * len(shape_context_costs)

    warped_pose_array = conversions.array_to_pose_array(f.transform_points(xyz_demo_ds), args.frame)
    Globals.handles = []
    import geometry_msgs.msg as gm
    for p, rgba in zip(warped_pose_array.poses, colors):
      ps = gm.PoseStamped()
      ps.header = warped_pose_array.header
      ps.pose = p
      Globals.handles.append(Globals.rviz.draw_marker(ps, scale=(.01, .01, .01), rgba=rgba))
#    Globals.handles.append(Globals.rviz.draw_curve(
#      warped_pose_array, rgba=colors, type=Marker.SPHERE_LIST
#    ))

if __name__ == '__main__':
  main()