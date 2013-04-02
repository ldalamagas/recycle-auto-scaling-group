recycle-auto-scaling-group
==========================

Python script to recycle ec2 instances in an Amazon (AWS) auto-scaling group using boto.

usage: recycle_autoscale_group [<autoscale group names>]
example: recycle_autoscale_group my-application-autoscale-group your-application-autoscale-group

This script temporarily increases a group's desired_capacity and max_size, 
recycles (terminates) ec2 instances in the group one by one while keeping the number of 'InService'
instances steady. As soon as recycling is complete group configuration is set to its previous values.
