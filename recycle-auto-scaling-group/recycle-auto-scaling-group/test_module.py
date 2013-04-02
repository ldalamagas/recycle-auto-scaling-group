'''
Created on Mar 30, 2013

@author: lefteris
'''
import recycle_autoscale_group

if __name__ == '__main__':
    autoscale_group_names = recycle_autoscale_group.get_arguments()
    group_name = autoscale_group_names[0]
    group = recycle_autoscale_group.get_autoscale_group(group_name)
    elb_names = group.load_balancers
    elb_name = elb_names[0]
    load_balancer = recycle_autoscale_group.get_elb(elb_name)
    instance_ids = recycle_autoscale_group.get_elb_instance_ids(elb_name) 