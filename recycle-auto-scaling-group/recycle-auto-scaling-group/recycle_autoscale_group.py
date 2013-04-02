#!/usr/bin/python
'''
Created on Mar 30, 2013

@author: lefteris
'''
import sys
import os.path
import time
from boto.ec2 import autoscale,elb
from boto import config,ec2

'''
About this script
'''
def get_script_name():
    return os.path.splitext(os.path.basename(__file__))[0]

def get_arguments():
    arguments = sys.argv
    script_name = get_script_name()
    
    # The first item in the list of arguments is myself
    # Let's check prior to remove, just in case I am called more than once
    if script_name in arguments[0]: arguments.pop(0)
    return arguments

def print_usage():
    script_name = get_script_name()
    print 'usage:', script_name, '[<autoscale group names>]'
    print 'example:', script_name, 'my-application-autoscale-group your-application-autoscale-group'
    
'''
About Autoscale Group
'''
def autoscale_group_exists(autoscale_group_name):
    connection = autoscale.connect_to_region(config.get_value('Boto', 'autoscale_region_name'))
    groups = connection.get_all_groups(names=[autoscale_group_name])
    return True if len(groups) == 1 else False

def is_valid_autoscale_region(region_name):
    regions = autoscale.regions()
    region_names = [region.name for region in regions]
    return True if region_name in region_names else False

def get_autoscale_group(autoscale_group_name):
    connection = autoscale.connect_to_region(config.get_value('Boto', 'autoscale_region_name'))
    groups = connection.get_all_groups(names=[autoscale_group_name])
    return groups[0]

def there_are_suspended_processes(autoscale_group):
    suspended_processes = autoscale_group.suspended_processes
    return True if len(suspended_processes) > 0 else False

'''
About Elastic Load Balancer
'''
def is_valid_elb_region(region_name):
    regions = elb.regions()
    region_names = [region.name for region in regions]
    return True if region_name in region_names else False

def get_elb(load_balancer_name):
    connection = elb.connect_to_region(config.get_value('Boto', 'elb_region_name'))
    load_balancers = connection.get_all_load_balancers(load_balancer_names=[load_balancer_name])
    return load_balancers[0]

def elb_exists(load_balancer_name):
    connection = elb.connect_to_region(config.get_value('Boto', 'elb_region_name'))
    load_balancers = connection.get_all_load_balancers(load_balancer_names=[load_balancer_name])
    return True if len(load_balancers) == 1 else False

def get_elb_instance_states(load_balancer_name):
    # Get a fresh representantion of the load balancer
    load_balancer = get_elb(load_balancer_name)
    return load_balancer.get_instance_health()

def get_elb_instance_state(load_balancer_name, instance_id):
    # Get a fresh representantion of the load balancer
    load_balancer = get_elb(load_balancer_name)
    return load_balancer.get_instance_health(instances=[instance_id])[0]
    
def get_elb_instance_ids(load_balancer_name):
    # Get a fresh representantion of the load balancer
    load_balancer = get_elb(load_balancer_name)
    instance_states = load_balancer.get_instance_health()
    return [instance_state.instance_id for instance_state in instance_states]   

def are_there_out_of_service_instances(load_balancer_name):
    # Get a fresh representantion of the load balancer
    load_balancer = get_elb(load_balancer_name)
    elb_instance_states = load_balancer.get_instance_health()
    
    for elb_instance_state in elb_instance_states:
        if elb_instance_state.state != 'InService':
            return True
    return False

def get_elb_in_service_instance_states(load_balancer_name):
    # Get a fresh representantion of the load balancer
    load_balancer = get_elb(load_balancer_name)
    elb_instance_states = load_balancer.get_instance_health()
    in_service_states = []
    for elb_instance_state in elb_instance_states:
        if elb_instance_state.state == 'InService':
            in_service_states.append(elb_instance_state)
    return in_service_states

'''
About EC2
'''
def is_valid_ec2_region(region_name):
    regions = ec2.regions()
    region_names = [region.name for region in regions]
    return True if region_name in region_names else False

def terminate_instance(instance_id):
    connection = ec2.connect_to_region(config.get_value('Boto', 'ec2_region_name'))
    connection.terminate_instances(instance_ids=[instance_id])

def recycle_autoscale_group(autoscale_group_name):
    
    polling_internval = 5 # In seconds
    # In seconds, the time need to deregister an instance from the load balancer
    elb_deregistration_interval = 30
    # In seconds, = 10 minutes. 
    # The time i need to create the instance, install the services and be picked up by the load balancer
    elb_registration_interval = 600
    
    print 'Recycling Group <', autoscale_group_name, '>'
    
    '''
    Group Checks
    '''
    # Does the group exist?
    if not autoscale_group_exists(autoscale_group_name):
        print 'Autoscale Group <', autoscale_group_name, \
        '> either does not exist, or more than one results found for the given name. I will just skip it\n'
        return

    group = get_autoscale_group(autoscale_group_name)
    
    # Are there any suspended processes for this group?
    if there_are_suspended_processes(group):
        print 'There are suspended processes for this group. I cannot continue recycling it, so I will just skip it\n'
        return
    
    # Keep current configuration so we can set it back later
    if group.max_size == None:
        group_max_size = group.desired_capacity
    else:
        group_max_size = group.max_size
    group_desired_capacity = group.desired_capacity
    
    temp_size_increment = 1
    temp_desired_capacity = group_desired_capacity + temp_size_increment
    temp_max_size = 0
    
    if group_max_size == 0:
        print 'Current maximum capacity is 0, there is nothing to recycle. I will just skip the group\n'
        return
    if group_desired_capacity == 0:
        print 'Current maximum capacity is 0, there is nothing to recycle. I will just skip the group\n'
        return
    
    '''
    Load Balancer Checks
    '''
    load_balancer_names = group.load_balancers
    print 'Load balancers', load_balancer_names
    if len(load_balancer_names) > 1:
        print 'There are more than one load balancers on this group, sorry but I do not know what to do. You better check this out'
        print 'I will skip this group'
        return
    load_balancer_name = load_balancer_names[0]
    
    # Does the load balancer exist? 
    # Ok it probably does, but we have to make sure the is only one with the given name
    if not elb_exists(load_balancer_name):
        print 'Load balancer <', load_balancer_name, \
        '> either does not exist, or more than one results found for the given name. I will just skip this group\n'
        return
    
    load_balancer = get_elb(load_balancer_name)
    elb_instance_states = get_elb_instance_states(load_balancer_name)
    print 'Instance states:', [[instance_state.instance_id, instance_state.state] for instance_state in elb_instance_states]
    
    # Are there any not InService instances?
    if are_there_out_of_service_instances(load_balancer_name):
        print 'Since there are out of service instances on the load balancer I cannot risk starting the recycle'
        print 'I will skip this group'
        return

    '''
    Load Balancer Instances
    '''    
    # Get the current instance ids so we know what to terminate
    elb_instance_ids = get_elb_instance_ids(load_balancer_name)
    
    print "Group's desired capacity [", group_desired_capacity,'] has to be increased by [', \
    temp_size_increment, '] to [', temp_desired_capacity, ']'
    
    '''
    Maximum size
    '''
    if group_desired_capacity >= group_max_size:
        temp_max_size = group_max_size + temp_size_increment  
        print "Since that would exceed group's maximum size [", group_max_size, ']'
        print "I will increase group's maximum size [", group_max_size, '] by [', temp_size_increment, '] to [', temp_max_size, '] too'
        print "Increasing group's maximum size [", group_max_size, '] by [', temp_size_increment, '] to [', temp_max_size, ']'
        group.max_size = temp_max_size
    
    '''
    Desired capacity
    '''
    print "Increasing group's desired capacity [", group_desired_capacity, '] by [', temp_size_increment, '] to [', temp_desired_capacity, ']'
    group.desired_capacity = temp_desired_capacity
    
    '''
    Start Working
    '''
    print 'Updating group [', autoscale_group_name, ']' 
    group.update() # Update the group and wait for the new instance to come to <InService> state
    
    # Wait for AWS to create a new instance and add it to the load balancer as OutOfService
    print 'Wait for the new instance to show as an OutOfService instance on the load balancer'
    while len(get_elb_instance_states(load_balancer_name)) < temp_desired_capacity:
        print 'are we there yet?'
        time.sleep(polling_internval)
    
    # Get the new instance
    new_instance_states = get_elb_instance_states(load_balancer_name)
    for instance_state in new_instance_states:
        if instance_state.state == 'OutOfService':
            new_instance_state = instance_state
            break
        
    new_instance_id = new_instance_state.instance_id
    
    print 'New instance detected:', new_instance_id, 'now lets wait for it to become <InService>'
    # Give some time for the new instance to be created and picked up by the load balancer
    print 'Going to sleep for', elb_registration_interval, 'seconds while the new instance kicks in'
    time.sleep(elb_registration_interval)
    while get_elb_instance_state(load_balancer_name, new_instance_id).state != 'InService':
        print 'are we there yet?'
        time.sleep(polling_internval)
    
    print 'New instance has is now marked as <InService>. Time for us to start recycling'
    
    for elb_instance_id in elb_instance_ids:
        print ''
        print 'De-registering instance <', elb_instance_id, '> from load balancer <', load_balancer_name, '>'
        load_balancer.deregister_instances([elb_instance_id])
        # Sleep a bit while the operation completes
        time.sleep(elb_deregistration_interval)
        print 'Going to sleep for', elb_deregistration_interval, 'to wait for de-registration to complete'
        print 'Terminating instance <', elb_instance_id, '>'
        terminate_instance(elb_instance_id)
        print 'Going to sleep for', elb_registration_interval, 'seconds while the new instance kicks in'
        # Give some time for the new instance to be created and picked up by the load balancer
        time.sleep(elb_registration_interval)
        while len(get_elb_in_service_instance_states(load_balancer_name)) < temp_desired_capacity:
            print 'The instance is not ready yet, I will keep quering AWS every <', polling_internval, '> seconds'
            time.sleep(polling_internval)
        
        print 'Instance up and <InService>'
    
    print 'Recycling of instances is complete, I will now configure max size and desired capacity to their previous values'
    group = get_autoscale_group(autoscale_group_name)
    group.max_size = group_max_size
    group.desired_capacity = group_desired_capacity
    group.update()

def main():
    autoscale_group_names = get_arguments()

    if len(autoscale_group_names) == 0:
        print_usage()
        exit(0)
    
    # Check the configured autoscale region
    autoscale_region_name = config.get_value('Boto', 'autoscale_region_name')
    if not is_valid_autoscale_region(autoscale_region_name):
        print autoscale_region_name, 'is not a valid autoscale region name'
        exit(0)
        
    # Check the configured elb region
    elb_region_name = config.get_value('Boto', 'elb_region_name')
    if not is_valid_elb_region(elb_region_name):
        print elb_region_name, 'is not a valid elb region name'
        exit(0)
        
    # Check the configured ec2 region
    elb_region_name = config.get_value('Boto', 'ec2_region_name')
    if not is_valid_elb_region(elb_region_name):
        print elb_region_name, 'is not a valid ec2 region name'
        exit(0)
    
    # Use this execution if you do not need user confirmation
    #print 'I will recycle autoscale groups', autoscale_group_names
    #for autoscale_group_name in autoscale_group_names:
    #    recycle_autoscale_group(autoscale_group_name)
    #print 'Job Complete. Thanks for flying with us'
    #exit(0)
    
    # Use this execution instead if you need a user confirmation
    print 'If you continue I will recycle autoscale groups', autoscale_group_names
    valid_responses = ['y','n']
    response = ''
    
    while response not in valid_responses:
        response = raw_input('You better know what you are doing. Continue?[y/n]:')

    if response == 'n':
        print 'See ya!'
        exit(0)
    elif response == 'y':
        print ''
        for autoscale_group_name in autoscale_group_names:
            recycle_autoscale_group(autoscale_group_name)
        print 'Job Complete. Thanks for flying with us'
        exit(0)

if __name__ == '__main__':
    main()