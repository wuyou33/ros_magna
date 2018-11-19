#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
Created on Mon Feb 19 17:03:12 2018

@author: josmilrom
"""
import sys
import rospy
import std_msgs.msg
import time
import math
import numpy as np
import tf
# import rvo2
import rvo23d
import time
# from cv_bridge import CvBridge, CvBridgeError
from uav_abstraction_layer.srv import *
from geometry_msgs.msg import *
from sensor_msgs.msg import *
# import tensorflow as tflow
# from tensorflow.python.tools import inspesct_checkpoint as chkp

class Brain(object):
    def __init__(self,ID,role):
        # Local parameters inizialization from arguments
        self.ID = ID
        self.role = role

        self.GettingWorldDefinition()    # Global ROS parameters inizialization
        # self.timer_start = time.time()

        # If the solver is a neural network, make some additional initializations
        if self.solver_algorithm == "neural_network":
            self.session = tflow.Session()      # Start a TensorFlow session

            # Import the metagraph from specific path. In the future will be better path management
            new_saver = tflow.train.import_meta_graph("/home/josmilrom/Libraries/gml/Sessions/{0}/type{1}_Nuav{2}_Nobs{3}/model.meta"\
                                                      .format(self.role,self.world_type,self.N_uav,self.N_obs))

            # Restore to the last chechpoint
            new_saver.restore(self.session,tflow.train.latest_checkpoint('/home/josmilrom/Libraries/gml/Sessions/{0}/type{1}_Nuav{2}_Nobs{3}'\
                                                                         .format(self.role,self.world_type,self.N_uav,self.N_obs)))

            # Initialize inputs and outputs from graph
            self.graph_inputs = tflow.get_default_graph().get_tensor_by_name("single_input:0")
            self.graph_outputs = tflow.get_default_graph().get_tensor_by_name("vel_posttreated:0")

            # self.single_vel_logits_tensor = tflow.get_default_graph().get_tensor_by_name("single_vel_logits:0")


    # Function to decide which algorithm is used for new velocity depending on parameters
    def Guidance(self,uavs_list, goal):
        self.uavs_list = uavs_list
        self.goal = goal

        # print "loop time", time.time() - self.timer_start
        # self.timer_start = time.time()

        if self.solver_algorithm == "simple":
            return self.SimpleGuidance()

        elif self.solver_algorithm == "neural_network":
            return self.NeuralNetwork()

        elif self.solver_algorithm == "orca":
            return self.ORCA()

        elif self.solver_algorithm == "orca3":
            return self.ORCA3()

    # Function to set new velocity using a Neural Network
    def NeuralNetwork(self):

        # Definition of neural network's inputs and outputs for every role.
        # In the future this will be imported from a common place
        if self.role == "path":
            input_dicc = ['own_vel','goal_pose_rel','others_pos_rel','others_vel','obs_pos_rel']
            output_dicc = ["sel_vel"]
        elif self.role == "uav_ad":
            input_dicc = ['own_vel','goal_pose_rel','goal_vel','distance','others_pos_rel','others_vel','obs_pos_rel']
            output_dicc = ["sel_vel"]
        elif self.role == "uav_ap":
            input_dicc = ['own_vel','goal_pose_rel','goal_vel','others_pos_rel','others_vel','obs_pos_rel']

        output_dicc = ["sel_vel"]

        # Initialization of pos and vel that will be taken as inputs
        inputs = []
        main_uav_pos = self.uavs_list[self.ID-1].position.pose.position
        main_uav_vel = self.uavs_list[self.ID-1].velocity.twist.linear

        # For every input in the dictionary, crate if needed and add it to inputs
        for n_input in input_dicc:

            # own vel
            if n_input == "own_vel":
                inputs.append(main_uav_vel.x)
                inputs.append(main_uav_vel.y)
                inputs.append(main_uav_vel.z)

            # own goal
            elif n_input == "goal_pose_rel":
                inputs.append(self.goal["pose"].position.x-main_uav_pos.x)
                inputs.append(self.goal["pose"].position.y-main_uav_pos.y)
                inputs.append(self.goal["pose"].position.z-main_uav_pos.z)

            elif n_input == "goal_vel":
                inputs.append(self.goal["vel"].linear.x)
                inputs.append(self.goal["vel"].linear.y)
                inputs.append(self.goal["vel"].linear.z)

            elif n_input == "distance":
                inputs.append(self.goal["dist"])

            elif n_input == "others_pos_rel":
                for n_uav in range(self.N_uav):
                    if n_uav+1 != self.ID:
                        #pos
                        inputs.append(self.uavs_list[n_uav].position.pose.position.x-main_uav_pos.x)
                        inputs.append(self.uavs_list[n_uav].position.pose.position.y-main_uav_pos.y)
                        inputs.append(self.uavs_list[n_uav].position.pose.position.z-main_uav_pos.z)

            elif n_input == "others_vel":
                for n_uav in range(self.N_uav):
                    if n_uav+1 != self.ID:
                        #vel
                        inputs.append(self.uavs_list[n_uav].velocity.twist.linear.x)
                        inputs.append(self.uavs_list[n_uav].velocity.twist.linear.y)
                        inputs.append(self.uavs_list[n_uav].velocity.twist.linear.z)

            elif n_input == "obs_pos_rel":
                for n_obs in range(self.N_obs):
                    inputs.append(self.obs_pose_list[n_obs][0]-main_uav_pos.x)
                    inputs.append(self.obs_pose_list[n_obs][1]-main_uav_pos.y)
                    inputs.append(self.obs_pose_list[n_obs][2]-main_uav_pos.z)

        # Reshape the inputs to a single file
        inputs_trans = np.asarray(inputs)
        inputs_trans = inputs_trans.reshape((1, inputs_trans.shape[0]))

        # Run session once to predict new selected velocity
        selected_velocity = self.session.run(self.graph_outputs, feed_dict={self.graph_inputs:inputs_trans})

        # Depict the output into the defined variables
        output_index = 0
        for n_output in output_dicc:
            if n_output == "sel_vel":
                selected_velocity = selected_velocity[0][output_index:output_index+3]

                # Construct the twist
                new_velocity_twist = Twist(Vector3(selected_velocity[0],selected_velocity[1],selected_velocity[2]),Vector3(0,0,0))
                output_index += 3

        # print("nn",new_velocity_twist)
        # self.ORCA3()
        return new_velocity_twist

    # Function to set velocity using ORCA on 3D
    def ORCA3(self):

        # Give value to orca algorithm parameters
        timeStep = 0.3          # 1/60.  float   The time step of the simulation. Must be positive.
        neighborDist = 4.0      # 1.5    float   The maximal distance (center point to center point) to other agents the agent takes into account in the navigation
        maxNeighbors = 10        # 5      size_t  The maximal number of other agents the agent takes into account in the navigation
        timeHorizon = 10       # 2.5    float   The minimal amount of time for which the agent's velocities that are computed by the simulation are safe with respect to other agents.
        uav_radius = 0.5        # 2      float   The radius of the agent. Must be non-negative
        maxSpeed = 2.0          # 0.4    float   The maximum speed of the agent. Must be non-negative.
        velocity = (1, 1, 1)

        # Select obstacle radius depending on world type
        if self.world_type == 1:
            obs_radius = 0.5
        elif self.world_type == 3:
            obs_radius = 2.5

        # Create an object of orca3 solver class and give the above defined parameters
        sim = rvo23d.PyRVOSimulator(timeStep, neighborDist, maxNeighbors, timeHorizon, uav_radius, maxSpeed, velocity)

        # Select nearest UAVs and Neighbors
        agent_list = []
        uav_near_neighbors_sorted, obs_near_neighbors_sorted = self.NeighborSelector()

        prefered_velocity = self.SimpleGuidance() # Select a velocity directly to goal as if there weren't exist neighbors

        # Add to orca3 and to own list every agent created by own params
        agent_list = []
        for n_uas in uav_near_neighbors_sorted:
            agent_list.append(sim.addAgent((self.uavs_list[n_uas].position.pose.position.x, self.uavs_list[n_uas].position.pose.position.y,self.uavs_list[n_uas].position.pose.position.z),
            neighborDist, maxNeighbors, timeHorizon, uav_radius, maxSpeed, (0, 0, 0)))

        # Set the preferred velocity of own UAV as decided avobe
        sim.setAgentPrefVelocity(agent_list[0],(prefered_velocity.linear.x,prefered_velocity.linear.y,prefered_velocity.linear.z))

        # Set the preferred velocity of the rest of UAVs as the actual
        for n_uas in range(1,len(uav_near_neighbors_sorted)):
            sim.setAgentPrefVelocity(agent_list[n_uas],(self.uavs_list[uav_near_neighbors_sorted[n_uas]].velocity.twist.linear.x,self.uavs_list[uav_near_neighbors_sorted[n_uas]].velocity.twist.linear.y,self.uavs_list[uav_near_neighbors_sorted[n_uas]].velocity.twist.linear.z))

        # Add to orca3 and to own list every obstacle created by own params
        for n_obs in obs_near_neighbors_sorted:
            obs_pose = self.obs_pose_list[n_obs]
            agent_list.append(sim.addAgent((obs_pose[0],obs_pose[1],obs_pose[2]),
            neighborDist, maxNeighbors, timeHorizon, obs_radius, 0.0, (0, 0, 0)))

        sim.doStep()        # Perform a step of orca3

        selected_velocity = sim.getAgentVelocity(agent_list[0])     # Extract own velocity decided by orca3

        # Become that velocity in a twist
        new_velocity_twist = Twist(Vector3(0,0,0),Vector3(0,0,0))
        new_velocity_twist.linear.x = selected_velocity[0]
        new_velocity_twist.linear.y = selected_velocity[1]
        new_velocity_twist.linear.z = selected_velocity[2]

        # If head use selected, decide it by direct by simple algorithm
        if self.heading_use == True:
            new_velocity_twist.angular.z = prefered_velocity.angular.z

        return new_velocity_twist

    # Function to set velocity directly to goal
    def SimpleGuidance(self):

        # Set algorithm params
        desired_velocity_module = 2
        desired_velocity_module_at_goal = 0
        aprox_distance = 3

        # Create a vector from actual position to goal position
        relative_distance = np.asarray([self.goal["pose"].position.x-self.uavs_list[self.ID-1].position.pose.position.x,\
                                self.goal["pose"].position.y-self.uavs_list[self.ID-1].position.pose.position.y,\
                                self.goal["pose"].position.z-self.uavs_list[self.ID-1].position.pose.position.z])

        distance_norm = np.linalg.norm(relative_distance)       # Calculate its norm

        # If at a distance shorter than aproximation distance, reduce the velocity module
        if distance_norm < aprox_distance:
            desired_velocity_module = desired_velocity_module_at_goal - (desired_velocity_module - desired_velocity_module_at_goal)\
                                    + ((desired_velocity_module - desired_velocity_module_at_goal) *2) / (1 + math.exp(-5*distance_norm/aprox_distance))

        # Multiply each axis by the velocity module
        relative_WP_linear=Vector3(relative_distance[0]/distance_norm*desired_velocity_module,\
                                relative_distance[1]/distance_norm*desired_velocity_module,\
                                relative_distance[2]/distance_norm*desired_velocity_module)

        # Transform it in a pose position and calculate its orientation in Euler angles
        relative_WP_pose_degrees=Pose(relative_WP_linear,\
                                Vector3(np.arctan2(relative_WP_linear.z,relative_WP_linear.y),\
                                np.arctan2(relative_WP_linear.x,relative_WP_linear.z),\
                                np.arctan2(relative_WP_linear.y,relative_WP_linear.x)))  #### COMPROBAR ANGULOS

        # Transform the orientation from Eurler angles to quaternions
        orientation_list = [self.uavs_list[self.ID-1].position.pose.orientation.x, self.uavs_list[self.ID-1].position.pose.orientation.y, self.uavs_list[self.ID-1].position.pose.orientation.z, self.uavs_list[self.ID-1].position.pose.orientation.w]
        euler = tf.transformations.euler_from_quaternion(orientation_list)

        # Create the velocity twist with calculated data
        new_velocity_twist = Twist(relative_WP_pose_degrees.position,\
                                   Vector3(0,\
                                   0,\
                                   relative_WP_pose_degrees.orientation.z-euler[2]))

        # Thresholds imposition
        # new_velocity_twist.linear.x = self.UpperLowerThresholds(new_velocity_twist.linear.x,1.5)
        # new_velocity_twist.linear.y = self.UpperLowerThresholds(new_velocity_twist.linear.y,1.5)
        # new_velocity_twist.angular.z = self.UpperLowerThresholds(new_velocity_twist.angular.z,0.5)

        return new_velocity_twist

    # Function to set new velocity using ORCA on 2D
    # def ORCA(self):

    #     # start = time.time()
    #     sim = rvo2.PyRVOSimulator(0.3,     # 1/60.  float   timeStep           The time step of the simulation. Must be positive.
    #                             4.0,     # 1.5    float   neighborDist       The maximal distance (center point to center point) to other agents the agent takes into account in the navigation
    #                             4,       # 5      size_t  maxNeighbors       The maximal number of other agents the agent takes into account in the navigation
    #                             2.5,     # 1.5    float   timeHorizon        The minimal amount of time for which the agent's velocities that are computed by the simulation are safe with respect to other agents.
    #                             2.5,     # 2      float   timeHorizonObst    The minimal amount of time for which the agent's velocities that are computed by the simulation are safe with respect to obstacles.
    #                             0.5,     # 0.4    float   radius             The radius of the agent. Must be non-negative
    #                             2.0)     # 2      float   maxSpeed           The maximum speed of the agent. Must be non-negative.

    #     # antiguo para 1-2: 1/60. 3.0 4 1.5 2.5 0.5 2.0

    #     agent_list = []
    #     for n_uas in np.arange(self.N_uav):
    #         agent_list.append(sim.addAgent((self.uavs_list[n_uas].position.pose.position.x, self.uavs_list[n_uas].position.pose.position.y)))
    #         # tuple pos, neighborDist=None,
    #         # maxNeighbors=None, timeHorizon=None,
    #         # timeHorizonObst=None, radius=None, maxSpeed=None,
    #         # velocity=None

    #     # Obstacles
    #     for n_obs in np.arange(self.N_obs):
    #         obs_reduced_list = []
    #         obs_raduis = 1
    #         obs_pose = self.obs_pose_list[n_obs]
    #         circle_division = 16
    #         for n in np.arange(circle_division):
    #             obs_reduced_list.append((obs_pose[0]+obs_raduis*np.cos(2*np.pi*n/circle_division),obs_pose[1]+obs_raduis*np.sin(2*np.pi*n/circle_division)))
    #         sim.addObstacle(obs_reduced_list)

    #     sim.processObstacles()

    #     for n_uas in np.arange(self.N_uav):
    #         if n_uas == self.ID-1:
    #             prefered_velocity = self.SimpleGuidance()
    #             sim.setAgentPrefVelocity(agent_list[n_uas],(prefered_velocity.linear.x,prefered_velocity.linear.y))
    #         else:
    #             sim.setAgentPrefVelocity(agent_list[n_uas],(self.uavs_list[n_uas].velocity.twist.linear.x,self.uavs_list[n_uas].velocity.twist.linear.y))

    #     sim.doStep()
    #     selected_velocity = sim.getAgentVelocity(self.ID-1)
    #     new_velocity_twist = Twist(Vector3(0,0,prefered_velocity.linear.z),Vector3(0,0,0))
    #     new_velocity_twist.linear.x = selected_velocity[0]
    #     new_velocity_twist.linear.y = selected_velocity[1]

    #     # finish = time.time()
    #     # print finish - start

    #     return new_velocity_twist

    # Function to set hovering velocity equal to zeros
    def Hover(self):
        new_velocity_twist = Twist(Vector3(0,0,0),Vector3(0,0,0))

        return new_velocity_twist

    # Function to saturate a value
    def UpperLowerThresholds(self,value,threshold):
        if value > threshold:
            value = threshold
        elif value < -threshold:
            value = -threshold
        return value

    def NeighborSelector(self):
        own_pose = self.uavs_list[self.ID-1].position.pose.position
        uav_distances = []
        for n_uav in range(self.N_uav):
            agent_pose = self.uavs_list[n_uav].position.pose.position
            Distance = math.sqrt((agent_pose.x-own_pose.x)**2+(agent_pose.y-own_pose.y)**2+(agent_pose.z-own_pose.z)**2)
            uav_distances.append(Distance)
        uav_distances_sorted = list(np.argsort(uav_distances))[:self.N_uav]

        obs_distances = []
        for n_obs in range(self.N_obs):
            obs_pos = self.obs_pose_list[n_obs]
            Distance = math.sqrt((obs_pos[0]-own_pose.x)**2+(obs_pos[1]-own_pose.y)**2+(obs_pos[2]-own_pose.z)**2)
            obs_distances.append(Distance)
        obs_distances_sorted = list(np.argsort(obs_distances))[:self.N_obs]

        return uav_distances_sorted, obs_distances_sorted

    # Function to get Global ROS parameters
    def GettingWorldDefinition(self):
        self.world_definition = rospy.get_param('world_definition')
        self.mission = self.world_definition['mission']
        self.world_type = self.world_definition['type']
        self.n_simulation = self.world_definition['n_simulation']
        self.N_uav = self.world_definition['N_uav']
        self.N_obs = self.world_definition['N_obs']
        self.n_dataset = self.world_definition['n_dataset']
        self.solver_algorithm = self.world_definition['solver_algorithm']
        self.obs_pose_list = self.world_definition['obs_pose_list']
        self.home_path = self.world_definition['home_path']
        self.heading_use = self.world_definition['heading_use']
