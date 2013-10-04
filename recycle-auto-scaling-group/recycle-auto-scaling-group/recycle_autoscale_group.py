#!/usr/bin/python
import argparse
import time
import logging
from boto.ec2 import autoscale, elb
from boto import config, ec2
from datetime import datetime, timedelta

logger = logging.getLogger("backup")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("AWS-RECYCLER[%(process)d] %(levelname)s: %(message)s")
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(fmt=formatter)
logger.addHandler(stream_handler)

recycle_timeout = 30 * 60               # In Seconds, 30 minutes
wait_a_bit_interval = 10                # In Seconds
polling_interval = 10                   # In seconds

start_time = datetime.now()


class AwsError(Exception):
    pass


class AutoscaleError(AwsError):
    pass

    class CannotGetConnection(AwsError):
        pass

    class GroupNotFound(AwsError):
        pass

    class MoreThanOneGroupWithSameName(AwsError):
        pass


class EC2Error(AwsError):
    pass

    class CannotGetConnection(AwsError):
        pass


class ELBError(AwsError):
    pass

    class CannotGetConnection(AwsError):
        pass

    class ELBNotFound(AwsError):
        pass

    class MoreThanOneELBFound(AwsError):
        pass


def wait_a_bit():
    time.sleep(wait_a_bit_interval)


def get_arguments():
    parser = argparse.ArgumentParser(description="AWS Auto Scaling Group Recycler")
    parser.add_argument('groups', help="The list of groups to recycle separated by 'space'", nargs="+")
    arguments = parser.parse_args()
    return arguments.groups


# About Autoscale Group
def get_autoscale_connection():
    connection = autoscale.connect_to_region(config.get_value('Boto', 'autoscale_region_name'))
    if connection is None:
        raise AutoscaleError.CannotGetConnection("cannot get autoscale connection. invalid 'autoscale_region_name'?")
    else:
        return connection


def get_autoscale_regions():
    region_objects = autoscale.regions()
    regions = [region_object.name for region_object in region_objects]
    return regions


def autoscale_group_exists(autoscale_group_name):
    connection = get_autoscale_connection()
    groups = connection.get_all_groups(names=[autoscale_group_name])
    connection.close()
    return True if len(groups) == 1 else False


def get_autoscale_group(autoscale_group_name):
    connection = get_autoscale_connection()
    groups = connection.get_all_groups(names=[autoscale_group_name])
    connection.close()
    if len(groups) == 1:
        return groups[0]
    elif len(groups) > 1:
        message = "more than one groups returned for [%s]" % autoscale_group_name
        raise AutoscaleError.MoreThanOneGroupWithSameName(message)
    elif len(groups) == 0:
        message = "no groups returned for [%s]" % autoscale_group_name
        raise AutoscaleError.GroupNotFound(message)


def get_autoscale_groups():
    connection = get_autoscale_connection()
    groups = connection.get_all_groups()
    connection.close()
    return groups


def there_are_suspended_processes(autoscale_group):
    suspended_processes = autoscale_group.suspended_processes
    return True if len(suspended_processes) > 0 else False


# About Elastic Load Balancer
def get_elb_connection():
    connection = elb.connect_to_region(config.get_value('Boto', 'elb_region_name'))
    if connection is None:
        raise ELBError.CannotGetConnection("cannot get elb connection. invalid 'elb_region_name'?")
    else:
        return connection


def get_elb_regions():
    region_objects = elb.regions()
    regions = [region_object.name for region_object in region_objects]
    return regions


def get_elb(load_balancer_name):
    connection = get_elb_connection()
    load_balancers = connection.get_all_load_balancers(load_balancer_names=[load_balancer_name])
    connection.close()
    if len(load_balancers) == 1:
        return load_balancers[0]
    elif len(load_balancers) > 1:
        message = "more than one load balancers found with name %s" % load_balancer_name
        raise ELBError.MoreThanOneELBFound(message)
    elif len(load_balancers) == 0:
        message = "no load balancers found with name %s" % load_balancer_name
        raise ELBError.ELBNotFound(message)
    return load_balancers[0]


def get_elb_name_from_group(group):
    load_balancers = group.load_balancers
    if len(load_balancers) == 1:
        return load_balancers[0]
    elif len(load_balancers) > 1:
        message = "there are more than one load balancers for group %s" % group.name
        raise ELBError.MoreThanOneELBFound(message)
    elif len(load_balancers) == 0:
        message = "no load balancers found for group %s" % group.name
        raise ELBError.ELBNotFound(message)


def get_elb_from_group(group):
    load_balancer_names = group.load_balancers
    if len(load_balancer_names) == 1:
        return get_elb(load_balancer_names[0])
    elif len(load_balancer_names) > 1:
        message = "there are more than one load balancers for group %s" % group.name
        raise ELBError.MoreThanOneELBFound(message)
    elif len(load_balancer_names) == 0:
        message = "no load balancers found for group %s" % group.name
        raise ELBError.ELBNotFound(message)


def get_elb_instance_states(load_balancer_name):
    # Get a fresh representantion of the load balancer
    load_balancer = get_elb(load_balancer_name)
    return load_balancer.get_instance_health()


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


# About EC2
def get_ec2_connection():
    connection = ec2.connect_to_region(config.get_value('Boto', 'ec2_region_name'))
    if connection is None:
        raise EC2Error.CannotGetConnection("cannot get ec2 connection. invalid 'elb_region_name'?")
    else:
        return connection


def terminate_instance(instance_id):
    connection = get_ec2_connection()
    connection.terminate_instances(instance_ids=[instance_id])
    connection.close()


def recycle_autoscale_group(autoscale_group_name):

    logger.info("recycling group '%s'", autoscale_group_name)
    group = None
    try:
        group = get_autoscale_group(autoscale_group_name)
    except (AutoscaleError.GroupNotFound, AutoscaleError.MoreThanOneGroupWithSameName) as error:
        logger.error(". ".join([error.message, "i will just skip it"]))
        return
    except AutoscaleError.CannotGetConnection as error:
        logger.error(". ".join([error.message, "i will stop"]))
        logger.info("valid autoscale regions are [%s]", get_autoscale_regions())
        exit(1)

    # Are there any suspended processes for this group?
    if there_are_suspended_processes(group):
        message = "there are suspended processes for group %s. I cannot recycle it, so I will just skip it" % group.name
        logger.warn(message)
        return

    # Keep current configuration so we can set it back later
    if group.max_size is None:
        group_max_size = group.desired_capacity
    else:
        group_max_size = group.max_size
    group_desired_capacity = group.desired_capacity

    temp_size_increment = 1
    temp_desired_capacity = group_desired_capacity + temp_size_increment

    if group_max_size == 0:
        logger.warn("current maximum size is 0, there is nothing to recycle. i will just skip the group")
        return
    if group_desired_capacity == 0:
        logger.warn("current maximum capacity is 0, there is nothing to recycle. i will just skip the group")
        return

    # Load Balancer
    load_balancer_name = None
    load_balancer = None
    try:
        load_balancer = get_elb_from_group(group)
        load_balancer_name = load_balancer.name
    except (ELBError.ELBNotFound, ELBError.MoreThanOneELBFound) as error:
        logger.error(". ".join([error.message, "sorry but i do not know what to do. i will skip this group"]))
        return
    except ELBError.CannotGetConnection as error:
        logger.error(". ".join([error.message, "i will exit"]))
        logger.info("valid elb regions are [%s]", get_elb_regions())
        exit(1)

    logger.info("load balancer is [%s]", load_balancer_name)

    elb_instance_states = get_elb_instance_states(load_balancer_name)
    logger.info("instance states: %s",
                [[instance_state.instance_id, instance_state.state] for instance_state in elb_instance_states])

    # Are there any instances that are not InService?
    if are_there_out_of_service_instances(load_balancer_name):
        logger.error("there are out of service instances on the elb,"
                     "please solve the issue before trying again i will skip this group")
        return

    # Desired Capacity
    logger.info("group's desired capacity [%s] has to be increased by [%s] to [%s]",
                group_desired_capacity, temp_size_increment, temp_desired_capacity)

    # Maximum size
    if group_desired_capacity >= group_max_size:
        temp_max_size = group_max_size + temp_size_increment
        logger.info("since that would exceed group's maximum size [%s] "
                    "i will increase group's maximum size [%s] by [%s] to [%s]",
                    group_max_size, group_max_size, temp_size_increment, temp_max_size)
        logger.info("increasing group's maximum size [%s] by [%s] to [%s]",
                    group_max_size, temp_size_increment, temp_max_size)
        group.max_size = temp_max_size

    # Desired capacity
    logger.info("increasing group's desired capacity [%s] by [%s] to [%s]",
                group_desired_capacity, temp_size_increment, temp_desired_capacity)
    group.desired_capacity = temp_desired_capacity

    # Start Working
    logger.info("updating group [%s]", autoscale_group_name)

    # Get the current instance ids so we know what to terminate
    elb_instance_ids = get_elb_instance_ids(load_balancer_name)
    logger.info("while recycling i am going to terminate the following instances %s", elb_instance_ids)

    group.update()  # Perform the changes
    wait_a_bit()    # Wait for the scaling activity to initiate

    for elb_instance_id in elb_instance_ids:
        loop_start_time = datetime.now()

        # Wait for the new instance to show up on load balancer
        logger.info("waiting for new instance to show up")
        while len(get_elb_instance_states(load_balancer_name)) != temp_desired_capacity:
            # Are we out of time?
            if (datetime.now() - loop_start_time) > timedelta(seconds=recycle_timeout):
                logger.error("recycle action timed out, please solve the problem before retrying")
                exit(1)
            else:
                time.sleep(polling_interval)

        # Wait for all the instances to be <InService>
        logger.info("waiting for new instance to become <InService>")
        while are_there_out_of_service_instances(load_balancer_name):
            # Are we out of time?
            if (datetime.now() - loop_start_time) > timedelta(seconds=recycle_timeout):
                logger.error("recycle action timed out, please solve the problem before retrying")
                exit(1)
            else:
                time.sleep(polling_interval)

        # All of the instances are now <InService>
        logger.info("new instance has is now marked as <InService>. time for us to start recycling")
        logger.info("de-registering instance <%s> from load balancer <%s>", elb_instance_id, load_balancer_name)
        load_balancer.deregister_instances([elb_instance_id])
        wait_a_bit()
        logger.info("terminating instance <%s>", elb_instance_id)
        terminate_instance(elb_instance_id)
    logger.info("recycling of instances is complete,"
                "i will now configure max size and desired capacity to their previous values")
    group = get_autoscale_group(autoscale_group_name)
    group.max_size = group_max_size
    group.desired_capacity = group_desired_capacity
    group.update()


def main():
    autoscale_group_names = get_arguments()

    logger.info("i will recycle autoscale groups [%s]", autoscale_group_names)

    for autoscale_group_name in autoscale_group_names:
        recycle_autoscale_group(autoscale_group_name)

    duration = datetime.now() - start_time
    logger.info("job complete in %s minutes", (duration.total_seconds()/60))  # In minutes
    exit(0)

if __name__ == '__main__':
    main()
